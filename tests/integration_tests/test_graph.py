"""Behavioral and process-restart tests against real LangGraph checkpoints."""

import json
import os
import sqlite3
import subprocess
import sys

import pytest
from langgraph.types import Command

from agent.backends import DemoBackend
from agent.governance import PolicyError
from agent.runtime import Runtime

TICKET = {
    "ticket_id": "T-1",
    "subject": "Upload error",
    "description": "The file upload fails.",
}
REVIEWER = {"id": "maya", "team": "support", "role": "reviewer"}


def approve(runtime, thread="run-1"):
    info = runtime.inspect(thread)
    return runtime.review(thread, REVIEWER, info["state"]["proposal_hash"])


def count_replies(data):
    with sqlite3.connect(data / "delivery-simulator.sqlite") as db:
        return db.execute("SELECT COUNT(*) FROM replies").fetchone()[0]


def test_model_approval_does_not_release_a_reply(tmp_path):
    with Runtime(tmp_path, demo=True) as runtime:
        info = runtime.submit("run-1", TICKET)
        assert info["state"]["model_status"] == "approved"
        assert info["state"]["status"] == "awaiting_approval"
        assert info["next"] == ["human_review"]
        assert "body" not in info["state"]["message"]
        with pytest.raises(PolicyError):
            runtime.deliver("run-1")
        assert count_replies(tmp_path) == 0
        approve(runtime)
        first = runtime.deliver("run-1")
        second = runtime.deliver("run-1")
        assert first["reply_id"] == second["reply_id"]
        assert second["already_completed"]
        assert count_replies(tmp_path) == 1


def test_awaiting_review_survives_closed_process_resources(tmp_path):
    with Runtime(tmp_path, demo=True) as runtime:
        original = runtime.submit("run-1", TICKET)
    with Runtime(tmp_path, demo=True) as runtime:
        recovered = runtime.resume("run-1")
        assert recovered["state"]["proposal_hash"] == original["state"]["proposal_hash"]
        assert recovered["state"]["review_count"] == 1
        approve(runtime)
        runtime.deliver("run-1")


@pytest.mark.parametrize(
    "actor",
    [
        {"id": "alex", "team": "support", "role": "contributor"},
        {"id": "sam", "team": "operations", "role": "reviewer"},
    ],
)
def test_wrong_role_or_team_cannot_approve(tmp_path, actor):
    with Runtime(tmp_path, demo=True) as runtime:
        info = runtime.submit("run-1", TICKET)
        with pytest.raises(PolicyError):
            runtime.review("run-1", actor, info["state"]["proposal_hash"])
        assert runtime.inspect("run-1")["next"] == ["human_review"]
        assert count_replies(tmp_path) == 0


def test_stale_hash_and_repeated_approval_are_rejected(tmp_path):
    with Runtime(tmp_path, demo=True) as runtime:
        runtime.submit("run-1", TICKET)
        with pytest.raises(PolicyError):
            runtime.review("run-1", REVIEWER, "stale")
        approve(runtime)
        with pytest.raises(PolicyError):
            approve(runtime)


def test_raw_boolean_resume_cannot_bypass_signing_authority(tmp_path):
    with Runtime(tmp_path, demo=True) as runtime:
        runtime.submit("run-1", TICKET)
        with pytest.raises(PolicyError, match="signed"):
            runtime.graph.invoke(Command(resume=True), runtime.config("run-1"))
        with pytest.raises(PolicyError):
            runtime.deliver("run-1")
        assert count_replies(tmp_path) == 0


def test_reject_prevents_delivery(tmp_path):
    with Runtime(tmp_path, demo=True) as runtime:
        info = runtime.submit("run-1", TICKET)
        result = runtime.review(
            "run-1", REVIEWER, info["state"]["proposal_hash"], "reject"
        )
        assert result["state"]["status"] == "rejected"
        with pytest.raises(PolicyError):
            runtime.deliver("run-1")


def test_proposal_tamper_after_approval_is_denied(tmp_path):
    with Runtime(tmp_path, demo=True) as runtime:
        runtime.submit("run-1", TICKET)
        approve(runtime)
        runtime.graph.update_state(
            runtime.config("run-1"),
            {"proposal": {"ticket_id": "T-1", "body": "A different reply"}},
        )
        with pytest.raises(PolicyError):
            runtime.deliver("run-1")
        assert count_replies(tmp_path) == 0


def test_ticket_thread_cannot_be_reused_for_other_input_or_backend(tmp_path):
    with Runtime(tmp_path, demo=True) as runtime:
        runtime.submit("run-1", TICKET)
        with pytest.raises(PolicyError):
            runtime.submit("run-1", {**TICKET, "ticket_id": "T-2"})
    with Runtime(tmp_path, demo=False) as runtime:
        with pytest.raises(PolicyError):
            runtime.inspect("run-1")


class PrivateBackend(DemoBackend):
    def retrieve(self, state):
        return [
            {
                "page_content": "Internal incident details",
                "source": "private:incident",
                "visibility": "private",
            }
        ]


class RejectedBackend(DemoBackend):
    def review(self, state):
        return {
            "status": "rejected",
            "feedback": "Unsupported answer",
            "retrive_improve": [],
        }


@pytest.mark.parametrize(
    "backend,ticket",
    [
        (PrivateBackend(), TICKET),
        (DemoBackend(), {**TICKET, "description": "My account was hacked"}),
        (RejectedBackend(), TICKET),
    ],
)
def test_unsafe_or_unreviewable_reply_escalates_without_approval_path(
    tmp_path, backend, ticket
):
    with Runtime(tmp_path, demo=True, backend=backend) as runtime:
        result = runtime.submit("run-1", ticket)
        assert result["state"]["status"] == "escalated"
        assert not result["next"]
        assert result["state"]["review_count"] <= 2
        with pytest.raises(PolicyError):
            runtime.review("run-1", REVIEWER, result["state"].get("proposal_hash", ""))
        assert count_replies(tmp_path) == 0


def test_failed_node_resumes_from_checkpoint_without_repeating_completed_nodes(
    tmp_path,
):
    class FailDraft(DemoBackend):
        def draft(self, state):
            raise TimeoutError("Injected model timeout")

    with Runtime(tmp_path, demo=True, backend=FailDraft()) as runtime:
        with pytest.raises(TimeoutError):
            runtime.submit("run-1", TICKET)

    class ResumeOnly(DemoBackend):
        def classify(self, state):
            raise AssertionError("Completed classification must not repeat")

        def retrieve(self, state):
            raise AssertionError("Completed retrieval must not repeat")

    with Runtime(tmp_path, demo=True, backend=ResumeOnly()) as runtime:
        result = runtime.resume("run-1")
        assert result["state"]["status"] == "awaiting_approval"
        events = [e["kind"] for e in result["audit"]]
        assert events.count("draft.started") == 2
        assert events.count("classify.started") == 1


def test_actual_process_death_after_effect_is_recovered_without_duplicate(tmp_path):
    with Runtime(tmp_path, demo=True) as runtime:
        runtime.submit("run-1", TICKET)
        approve(runtime)
    env = {**os.environ, "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}
    command = [
        sys.executable,
        "-m",
        "agent.runtime",
        "--demo",
        "--data",
        str(tmp_path),
        "deliver",
        "run-1",
    ]
    died = subprocess.run(
        command + ["--crash-after-effect"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert died.returncode == 86, died.stderr
    assert count_replies(tmp_path) == 1
    recovered = subprocess.run(
        command, capture_output=True, text=True, timeout=30, env=env
    )
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout)["deduplicated"] is True
    assert count_replies(tmp_path) == 1
    with Runtime(tmp_path, demo=True) as runtime:
        audit = runtime.inspect("run-1")["audit"]
        assert any(
            e["kind"] == "delivery.completed" and e["data"]["deduplicated"]
            for e in audit
        )


def test_concurrent_delivery_calls_share_one_effect(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    with Runtime(tmp_path, demo=True) as runtime:
        runtime.submit("run-1", TICKET)
        approve(runtime)

    def deliver(_):
        with Runtime(tmp_path, demo=True) as runtime:
            return runtime.deliver("run-1")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(deliver, range(2)))
    assert results[0]["reply_id"] == results[1]["reply_id"]
    assert count_replies(tmp_path) == 1


def test_delivery_checks_the_same_body_that_was_evaluated_and_approved(tmp_path):
    with Runtime(tmp_path, demo=True) as runtime:
        runtime.submit("run-1", TICKET)
        approve(runtime)
        runtime.graph.update_state(
            runtime.config("run-1"), {"draft": ["A new draft after approval"]}
        )
        with pytest.raises(PolicyError):
            runtime.deliver("run-1")
        assert count_replies(tmp_path) == 0

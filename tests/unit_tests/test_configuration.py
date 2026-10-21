"""Registration, routing and signed authority behavior."""

import copy
import time

import pytest

from agent.governance import (
    REGISTRATION,
    Authority,
    PolicyError,
    evaluate,
    validate_proposal,
    validate_registration,
)
from agent.graph import route_based_on_review

ACTOR = {"id": "maya", "team": "support", "role": "reviewer"}
PROPOSAL = {"ticket_id": "T-1", "body": "Please retry the upload."}


@pytest.mark.parametrize(
    "status,count,expected",
    [
        ("approved", 1, "prepare"),
        ("rejected", 2, "escalate"),
        ("rejected", 1, "retrieve"),
        ("rejected", 0, "retrieve"),
    ],
)
def test_route_is_a_synchronous_pure_decision(status, count, expected):
    assert (
        route_based_on_review({"model_status": status, "review_count": count})
        == expected
    )


@pytest.mark.parametrize("field", ["owner", "due_date", "status", "assignee"])
def test_proposal_has_no_commitment_update_fields(field):
    with pytest.raises(PolicyError):
        validate_proposal({**PROPOSAL, field: "anything"})


@pytest.mark.parametrize("field", ["owner", "team", "suite", "human_gate", "tools"])
def test_registration_cannot_omit_required_governance(field):
    entry = copy.deepcopy(REGISTRATION)
    entry.pop(field)
    with pytest.raises(PolicyError):
        validate_registration(entry)


def test_unknown_autonomy_class_and_tool_are_rejected():
    for changes in (
        {"tier": "autonomous"},
        {"tools": ["ticket.update"]},
        {"suite": "unknown"},
    ):
        with pytest.raises(PolicyError):
            validate_registration({**REGISTRATION, **changes})


def test_signed_review_is_bound_to_payload_thread_and_expiry():
    authority = Authority(b"a" * 32)
    receipt = authority.sign("one", PROPOSAL, ACTOR)
    assert authority.verify(receipt, "one", PROPOSAL) == "approve"
    for thread, proposal in [
        ("two", PROPOSAL),
        ("one", {**PROPOSAL, "body": "edited"}),
    ]:
        with pytest.raises(PolicyError):
            authority.verify(receipt, thread, proposal)
    expired = authority.sign("one", PROPOSAL, ACTOR, now=time.time() - 1000)
    with pytest.raises(PolicyError):
        authority.verify(expired, "one", PROPOSAL)
    with pytest.raises(PolicyError):
        authority.verify({**receipt, "actor": "attacker"}, "one", PROPOSAL)
    with pytest.raises(PolicyError):
        Authority(b"b" * 32).verify(receipt, "one", PROPOSAL)


@pytest.mark.parametrize(
    "change,expected",
    [
        ({}, True),
        ({"model_status": "rejected"}, False),
        ({"category": "security"}, False),
        ({"description": "Password leak"}, False),
        ({"draft": ["[Your name]"]}, False),
        ({"context_docs": []}, False),
        (
            {"context_docs": [{"page_content": "secret", "visibility": "private"}]},
            False,
        ),
    ],
)
def test_grade_the_policy_evaluator_with_labeled_examples(change, expected):
    safe = {
        "model_status": "approved",
        "category": "technical",
        "subject": "Upload",
        "description": "Upload failed",
        "draft": [PROPOSAL["body"]],
        "context_docs": [{"page_content": "retry", "visibility": "public"}],
    }
    assert evaluate({**safe, **change})["passed"] is expected

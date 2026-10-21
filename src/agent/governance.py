"""Trusted policy and reviewer authority. Models cannot mint approvals."""

import hashlib
import hmac
import json
import time

REGISTRATION = {
    "id": "support-drafter",
    "owner": "support-platform",
    "team": "support",
    "tier": "external_reply",
    "tools": ["reply.propose"],
    "suite": "support-v1",
    "human_gate": True,
}


class PolicyError(ValueError):
    """Reject unsupported capabilities or invalid authority."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def validate_registration(entry):
    if any(not entry.get(k) for k in ("id", "owner", "team", "tools", "suite")):
        raise PolicyError(
            "Registration needs an owner, team, tools and evaluation suite"
        )
    if entry.get("tier") != "external_reply" or entry.get("tools") != ["reply.propose"]:
        raise PolicyError("Only the reply-proposal capability is supported")
    if entry.get("suite") != "support-v1" or entry.get("human_gate") is not True:
        raise PolicyError("Known evaluation suite and human gate required")


def validate_proposal(proposal):
    if not isinstance(proposal, dict) or set(proposal) != {"ticket_id", "body"}:
        raise PolicyError(
            "A reply accepts only ticket_id and body; no commitment-update fields"
        )
    if not all(isinstance(v, str) and v.strip() for v in proposal.values()):
        raise PolicyError("Reply fields must be nonempty strings")
    if len(proposal["body"]) > 4000 or len(proposal["ticket_id"]) > 128:
        raise PolicyError("Reply exceeds supported limits")


def evaluate(state):
    body = state.get("draft", [""])[-1]
    docs = state.get("context_docs", [])
    checks = {
        "model_review": state.get("model_status", state.get("status")) == "approved",
        "nonempty_reply": isinstance(body, str) and 0 < len(body.strip()) <= 4000,
        "public_context": bool(docs)
        and all(d.get("visibility") == "public" for d in docs),
        "no_placeholders": isinstance(body, str)
        and not any(
            p in body.lower() for p in ("lorem ipsum", "[your name]", "[insert")
        ),
        "security_escalation": state.get("category") != "security"
        and not any(
            w in (state.get("subject", "") + " " + state.get("description", "")).lower()
            for w in ("hacking", "hacked", "breach", "password leak")
        ),
    }
    return {"suite": "support-v1", "checks": checks, "passed": all(checks.values())}


class Authority:
    """Sign receipts outside model state, bound to thread and exact body.

    The CLI trusts its local operator's asserted reviewer identity. Production
    must derive actor/team/role from authenticated identity, not CLI arguments.
    """

    def __init__(self, key: bytes):
        if len(key) < 32:
            raise PolicyError("Approval signing key must be at least 32 bytes")
        self.key = key

    def sign(self, thread_id, proposal, actor, decision="approve", now=None):
        validate_proposal(proposal)
        if (
            actor.get("team") != REGISTRATION["team"]
            or actor.get("role") != "reviewer"
            or not actor.get("id")
        ):
            raise PolicyError("A reviewer in the registered team must decide")
        if decision not in {"approve", "reject"}:
            raise PolicyError("Unknown review decision")
        payload = {
            "thread_id": thread_id,
            "proposal_hash": digest(proposal),
            "actor": actor["id"],
            "team": actor["team"],
            "decision": decision,
            "expires": (time.time() if now is None else now) + 900,
        }
        return {
            **payload,
            "signature": hmac.new(
                self.key, canonical(payload).encode(), hashlib.sha256
            ).hexdigest(),
        }

    def verify(self, receipt, thread_id, proposal, check_expiry=True):
        if not isinstance(receipt, dict) or set(receipt) != {
            "thread_id",
            "proposal_hash",
            "actor",
            "team",
            "decision",
            "expires",
            "signature",
        }:
            raise PolicyError("A signed human review receipt is required")
        payload = {k: v for k, v in receipt.items() if k != "signature"}
        signature = hmac.new(
            self.key, canonical(payload).encode(), hashlib.sha256
        ).hexdigest()
        if not isinstance(receipt["signature"], str) or not hmac.compare_digest(
            signature, receipt["signature"]
        ):
            raise PolicyError("Invalid approval signature")
        if (
            receipt["thread_id"] != thread_id
            or receipt["proposal_hash"] != digest(proposal)
            or receipt["team"] != REGISTRATION["team"]
        ):
            raise PolicyError("Approval is for another thread, team or payload")
        if (check_expiry and receipt["expires"] <= time.time()) or receipt[
            "decision"
        ] not in {"approve", "reject"}:
            raise PolicyError("Review receipt expired or decision is invalid")
        return receipt["decision"]

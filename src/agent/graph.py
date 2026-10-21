"""Checkpointable drafting graph. An LLM review never authorizes delivery."""

import os

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent.backends import LiveBackend
from agent.governance import (
    REGISTRATION,
    Authority,
    PolicyError,
    digest,
    evaluate,
    validate_proposal,
    validate_registration,
)
from agent.schemas import Input, Output
from agent.state import State


def route_based_on_review(state):
    if state.get("model_status", state.get("status")) == "approved":
        return "prepare"
    return "escalate" if state.get("review_count", 0) >= 2 else "retrieve"


def build_graph(checkpointer=None, backend=None, authority=None, audit=None):
    validate_registration(REGISTRATION)
    backend = backend or LiveBackend()

    def traced(kind, fn):
        def node(state, config):
            thread_id = str(config.get("configurable", {}).get("thread_id", ""))
            if audit:
                audit(
                    thread_id,
                    kind + ".started",
                    {k: v for k, v in state.items() if k != "receipt"},
                )
            result = fn(state)
            if audit:
                audit(thread_id, kind + ".completed", result)
            return result

        return node

    def classify(state):
        if not all(
            isinstance(state.get(k), str) and state[k].strip()
            for k in ("ticket_id", "subject", "description")
        ):
            raise ValueError("ticket_id, subject and description are required")
        category = backend.classify(state)
        if category not in {"billing", "technical", "security", "general"}:
            raise PolicyError("Model returned an invalid category")
        return {"category": category, "status": "drafting"}

    def retrieve(state):
        docs = backend.retrieve(state)
        if not isinstance(docs, list) or not all(
            isinstance(d, dict) and isinstance(d.get("page_content"), str) for d in docs
        ):
            raise PolicyError("Retriever must return serializable source records")
        return {"context_docs": docs}

    def draft(state):
        text = backend.draft(state)
        if not isinstance(text, str) or not text.strip():
            raise PolicyError("Model returned an empty or non-text draft")
        return {"draft": state.get("draft", []) + [text]}

    def review(state):
        result = backend.review(state)
        if result.get("status") not in {"approved", "rejected"}:
            raise PolicyError("Invalid model review result")
        return {
            "model_status": result["status"],
            "feedback": state.get("feedback", []) + [result.get("feedback") or ""],
            "review_count": state.get("review_count", 0) + 1,
        }

    def prepare(state):
        evaluation = evaluate(state)
        if not evaluation["passed"]:
            return {
                "evaluation": evaluation,
                "status": "escalated",
                "message": "Reply withheld: policy checks require manual handling.",
            }
        proposal = {"ticket_id": state["ticket_id"], "body": state["draft"][-1]}
        validate_proposal(proposal)
        return {
            "evaluation": evaluation,
            "proposal": proposal,
            "proposal_hash": digest(proposal),
            "status": "awaiting_approval",
            "message": "Reply withheld pending exact-payload human approval.",
        }

    def human_review(state, config):
        # Do not catch GraphInterrupt, perform effects or audit before interrupt:
        # this node starts again when the saved thread is resumed.
        receipt = interrupt(
            {
                "proposal": state["proposal"],
                "proposal_hash": state["proposal_hash"],
                "evaluation": state["evaluation"],
                "risk": REGISTRATION["tier"],
            }
        )
        signer = authority
        if signer is None:
            key = os.getenv("SUPPORT_APPROVAL_KEY", "").encode()
            signer = Authority(key)
        thread_id = str(config["configurable"]["thread_id"])
        decision = signer.verify(receipt, thread_id, state["proposal"])
        if audit:
            audit(
                thread_id,
                "human.reviewed",
                {
                    "actor": receipt["actor"],
                    "decision": decision,
                    "proposal_hash": state["proposal_hash"],
                },
            )
        return {
            "receipt": receipt,
            "status": "approved" if decision == "approve" else "rejected",
            "message": "Approved reply queued for the delivery broker."
            if decision == "approve"
            else "Human rejected the proposed reply; nothing delivered.",
        }

    def escalate(state):
        return {
            "status": "escalated",
            "evaluation": evaluate(state),
            "message": "Reply withheld: model review exhausted; manual handling required.",
        }

    builder = StateGraph(State, input_schema=Input, output_schema=Output)
    builder.add_node("classify", traced("classify", classify))
    builder.add_node("retrieve", traced("retrieve", retrieve))
    builder.add_node("draft", traced("draft", draft))
    builder.add_node("review", traced("model_review", review))
    builder.add_node("prepare", traced("evaluate", prepare))
    builder.add_node("human_review", human_review)
    builder.add_node("escalate", traced("escalate", escalate))
    builder.add_edge(START, "classify")
    builder.add_edge("classify", "retrieve")
    builder.add_edge("retrieve", "draft")
    builder.add_edge("draft", "review")
    builder.add_conditional_edges("review", route_based_on_review)
    builder.add_conditional_edges(
        "prepare",
        lambda s: "human_review" if s["status"] == "awaiting_approval" else END,
    )
    builder.add_edge("human_review", END)
    builder.add_edge("escalate", END)
    return builder.compile(checkpointer=checkpointer)


# Agent Server supplies its own persistence. The CLI explicitly uses SqliteSaver.
graph = build_graph()

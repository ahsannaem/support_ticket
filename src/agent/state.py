"""Serializable workflow state."""

from typing import Any

from typing_extensions import TypedDict


class State(TypedDict, total=False):
    ticket_id: str
    subject: str
    description: str
    category: str
    context_docs: list[dict[str, Any]]
    draft: list[str]
    review_count: int
    feedback: list[str]
    model_status: str
    status: str
    retrive_improve: list[str]
    evaluation: dict[str, Any]
    proposal: dict[str, str]
    proposal_hash: str
    receipt: dict[str, Any]
    message: str

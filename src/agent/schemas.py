"""Provider result and public graph schemas."""

from pydantic import BaseModel
from typing_extensions import Literal, TypedDict


class Classification(BaseModel):
    output: Literal["billing", "technical", "security", "general"]


class ReviewResult(BaseModel):
    status: Literal["approved", "rejected"]
    feedback: str
    retrive_improve: list[str]


class Input(TypedDict):
    ticket_id: str
    subject: str
    description: str


class Output(TypedDict):
    message: str
    status: str

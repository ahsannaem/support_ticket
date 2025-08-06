# agent/schemas.py

from typing import Optional, TypedDict
from pydantic import BaseModel
from typing_extensions import Literal

class Classification(BaseModel):
    output: Literal["billing", "technical", "security", "general"]

class ReviewResult(BaseModel):
    status: Literal["approved", "rejected"]
    feedback: Optional[str]

class Input(TypedDict):
    subject: str
    description: str

class Output(BaseModel):
    message: str

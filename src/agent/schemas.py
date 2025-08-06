# agent/schemas.py

from typing import List, Optional, TypedDict
from pydantic import BaseModel
from typing_extensions import Literal

class Classification(BaseModel):
    output: Literal["billing", "technical", "security", "general"]

class ReviewResult(BaseModel):
    status: Literal["approved", "rejected"]
    feedback: Optional[str]
    retrive_improve: Optional[List[str]]

class Input(TypedDict):
    subject: str
    description: str

class Output(BaseModel):
    message: str

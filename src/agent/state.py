
from dataclasses import dataclass
from pydantic import BaseModel
from dataclasses import dataclass, field
from typing import Literal, TypedDict, List



@dataclass(kw_only=True)
class State(TypedDict):
    """Represents state of our graph.

    Args:
        TypedDict (_type_): _description_
        Subject : The subject of support ticket
        description : The description of our support ticket
        classification (Literal["Billing", "Technical", "Security", "General"]):
            The classified category of the ticket.
        context (str): Relevant contextual information retrieved for the ticket.
        draft_response (str): The drafted response to the user.
        review_feedback (str): Feedback from the reviewer on the draft.
        retry_count (int): Number of times the draft has been re-attempted.
    """
    subject: str
    description: str
    category: Literal["billing", "technical", "security", "general"]
    context_docs:  str
    draft: List[str]
    review_count: int 
    feedback: List[str]
    status: Literal['approved','rejected']

import pytest
import os
from pathlib import Path
from agent.state import State
from agent.graph import dump_state_to_csv, route_based_on_review

@pytest.fixture
def sample_state():
    return State(
        subject="Test ticket",
        description="This is a test description",
        category="technical",
        context_docs=[],
        draft=[],
        feedback=[],
        review_count=0,
        status="pending"
    )

def test_route_based_on_review_approved(sample_state):
    sample_state["status"] = "approved"
    sample_state["review_count"] = 1
    result = route_based_on_review(sample_state)
    assert result == "format_output"

def test_route_based_on_review_max_reviews(sample_state):
    sample_state["status"] = "rejected"
    sample_state["review_count"] = 2
    result = route_based_on_review(sample_state)
    assert result == "dump_state"

def test_route_based_on_review_continue(sample_state):
    sample_state["status"] = "rejected"
    sample_state["review_count"] = 1
    result = route_based_on_review(sample_state)
    assert result == "retriver"

def test_route_based_on_review_zero_reviews(sample_state):
    sample_state["status"] = "rejected"
    sample_state["review_count"] = 0
    result = route_based_on_review(sample_state)
    assert result == "retriver"


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

def test_dump_state_to_csv_after_two_reviews(sample_state, tmp_path):
    sample_state["draft"] = ["Draft response"]
    sample_state["feedback"] = ["Feedback 1", "Feedback 2"]
    sample_state["review_count"] = 2
    sample_state["status"] = "rejected"

    # Ensure the rejected_tickets directory is created in tmp_path
    rejected_dir = tmp_path / "rejected_tickets"
    os.makedirs(rejected_dir, exist_ok=True)

    # Temporarily change the working directory to tmp_path for testing
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        updated_state = dump_state_to_csv(sample_state.copy())

        assert updated_state == sample_state
        csv_path = rejected_dir / "rejected_tickets.csv"
        assert csv_path.exists()
        csv_content = csv_path.read_text()
        assert "Test ticket" in csv_content
        assert "This is a test description" in csv_content
        assert "technical" in csv_content
        assert "Draft response" in csv_content
        assert "Feedback 1\n---\nFeedback 2" in csv_content
        assert "2" in csv_content
    finally:
        # Restore the original working directory and clean up
        os.chdir(original_cwd)
        if csv_path.exists():
            os.remove(csv_path)
            os.rmdir(rejected_dir)
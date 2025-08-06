import pytest
from pathlib import Path
from langchain.schema import Document
from agent.common import load_and_split_documents

def test_load_and_split_documents(tmp_path):
    # Create a temporary text file with sample content
    file_path = tmp_path / "test.txt"
    file_path.write_text("Intro text\nEntry 1: First entry content\nEntry 2: Second entry content")

    documents = load_and_split_documents(str(tmp_path))

    assert len(documents) == 2
    assert isinstance(documents[0], Document)
    assert documents[0].page_content == "First entry content"
    assert documents[0].metadata == {
        "category": "test",
        "entry": "1",
        "source": str(file_path)
    }
    assert documents[1].page_content == "Second entry content"
    assert documents[1].metadata == {
        "category": "test",
        "entry": "2",
        "source": str(file_path)
    }

def test_load_and_split_documents_empty(tmp_path):
    documents = load_and_split_documents(str(tmp_path))
    assert documents == []
"""Live adapter contracts with stubbed providers; no external API calls."""

from types import SimpleNamespace

from langchain_core.documents import Document

from agent.backends import LiveBackend
from agent.schemas import Classification, ReviewResult


class Model:
    def __init__(self):
        self.schema = None
        self.prompts = []

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, prompt):
        self.prompts.append(prompt.to_string())
        if self.schema is Classification:
            return Classification(output="technical")
        if self.schema is ReviewResult:
            return ReviewResult(
                status="approved", feedback="Grounded", retrive_improve=[]
            )
        return SimpleNamespace(content="Please retry the upload.")


def test_live_model_adapter_renders_context_and_returns_validated_outputs(monkeypatch):
    backend = LiveBackend()
    model = Model()
    monkeypatch.setattr(backend, "_llm", lambda: model)
    state = {
        "subject": "Upload",
        "description": "File fails",
        "context_docs": [
            {"page_content": "Refresh the application.", "visibility": "public"}
        ],
        "draft": ["Please retry the upload."],
    }
    assert backend.classify(state) == "technical"
    model.schema = None
    assert backend.draft(state) == "Please retry the upload."
    assert "Refresh the application." in model.prompts[-1]
    assert backend.review(state)["status"] == "approved"
    assert "Refresh the application." in model.prompts[-1]


def test_live_retrieval_preserves_visibility_and_does_not_default_to_public(
    monkeypatch,
):
    from agent import common

    observed = {}

    class Retriever:
        def invoke(self, query):
            observed["query"] = query
            return [
                Document(
                    page_content="public help",
                    metadata={"source": "help", "visibility": "public"},
                ),
                Document(page_content="unclassified", metadata={}),
            ]

    def factory(**kwargs):
        observed.update(kwargs)
        return Retriever()

    monkeypatch.setattr(common, "make_pgvector_retriever", factory)
    docs = LiveBackend().retrieve(
        {"subject": "Upload", "description": "fails", "category": "technical"}
    )
    assert observed["search_kwargs"]["filter"] == {"category": "technical"}
    assert [d["visibility"] for d in docs] == ["public", "unclassified"]

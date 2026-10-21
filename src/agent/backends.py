"""Injectable model/retrieval boundary. No delivery capability is provided."""

import os
from typing import Protocol

from langchain_core.prompts import PromptTemplate

from agent.prompts import (
    CLASSIFICATION_PROMPT,
    DRAFT_RESPONSE_PROMPT,
    REVIEW_DRAFT_PROMPT,
)
from agent.schemas import Classification, ReviewResult


class Backend(Protocol):
    def classify(self, state): ...
    def retrieve(self, state): ...
    def draft(self, state): ...
    def review(self, state): ...


class DemoBackend:
    """Explicit deterministic fixture for crash tests and the offline demo."""

    def classify(self, state):
        return "technical"

    def retrieve(self, state):
        return [
            {
                "page_content": "Refresh the application and retry uploading the file.",
                "source": "demo:upload-help",
                "visibility": "public",
            }
        ]

    def draft(self, state):
        return "Please refresh the application and retry uploading the file. If the issue persists, share the error message with support."

    def review(self, state):
        return {
            "status": "approved",
            "feedback": "Matches the public demo help text.",
            "retrive_improve": [],
        }


class LiveBackend:
    """Google model + existing pgvector index. Install the live extra to use it."""

    def _llm(self):
        from langchain_google_genai import ChatGoogleGenerativeAI

        model = os.getenv("GOOGLE_MODEL")
        if not model:
            raise ValueError("Set GOOGLE_MODEL to a model available to your account")
        return ChatGoogleGenerativeAI(
            model=model, temperature=0, max_retries=2, timeout=30
        )

    def classify(self, state):
        prompt = PromptTemplate.from_template(CLASSIFICATION_PROMPT).invoke(state)
        return self._llm().with_structured_output(Classification).invoke(prompt).output

    def retrieve(self, state):
        from agent.common import make_pgvector_retriever

        retriever = make_pgvector_retriever(
            search_kwargs={"filter": {"category": state["category"]}, "k": 5}
        )
        docs = retriever.invoke(state["subject"] + " " + state["description"])
        # Missing visibility stays unclassified and fails the outbound gate.
        return [
            {
                "page_content": d.page_content,
                "source": d.metadata.get("source", "unknown"),
                "visibility": d.metadata.get("visibility", "unclassified"),
            }
            for d in docs
        ]

    def draft(self, state):
        prompt = PromptTemplate.from_template(DRAFT_RESPONSE_PROMPT).invoke(
            {
                **state,
                "context": "\n\n".join(
                    d["page_content"] for d in state["context_docs"]
                ),
                "review": state.get("feedback", []),
            }
        )
        response = self._llm().invoke(prompt).content
        if not isinstance(response, str):
            raise ValueError("Draft provider returned non-text content")
        return response.strip()

    def review(self, state):
        prompt = PromptTemplate.from_template(REVIEW_DRAFT_PROMPT).invoke(
            {
                **state,
                "latest_draft": state["draft"][-1],
                "context": "\n\n".join(
                    d["page_content"] for d in state["context_docs"]
                ),
            }
        )
        return (
            self._llm().with_structured_output(ReviewResult).invoke(prompt).model_dump()
        )

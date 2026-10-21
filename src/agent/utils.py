"""Explicit live-provider/index helpers; never re-embed during ticket retrieval."""

import os

from agent.backends import LiveBackend
from agent.common import load_and_split_documents
from agent.governance import digest


def get_llm():
    return LiveBackend()._llm()


def refresh_rag(dataset_path="static/dataset", *, visibility):
    """Operator-classify documents before indexing; callers must choose visibility."""
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    from langchain_postgres import PGVector

    if visibility not in {"public", "private"}:
        raise ValueError("Explicit public/private source classification is required")
    connection = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection:
        raise ValueError("POSTGRES_CONNECTION_STRING is required")
    docs = load_and_split_documents(dataset_path)
    for doc in docs:
        doc.metadata["visibility"] = visibility
    store = PGVector(
        embeddings=GoogleGenerativeAIEmbeddings(
            model=os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
        ),
        collection_name="support_docs",
        connection=connection,
    )
    return store.add_documents(
        docs,
        ids=[
            digest({"source": d.metadata["source"], "entry": d.metadata["entry"]})
            for d in docs
        ],
    )

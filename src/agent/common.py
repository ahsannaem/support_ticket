"""Load documents without provider imports or import-time credential checks."""

import os
import re
from pathlib import Path

from langchain_core.documents import Document

POSTGRES_CONNECTION_STRING = os.getenv("POSTGRES_CONNECTION_STRING")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


def load_and_split_documents(dataset_path: str) -> list[Document]:
    docs = []
    for path in sorted(Path(dataset_path).rglob("*.txt")):
        entries = re.split(r"\bEntry\s+(\d+):", path.read_text(encoding="utf-8"))
        for i in range(1, len(entries), 2):
            docs.append(
                Document(
                    page_content=entries[i + 1].strip(),
                    metadata={
                        "category": path.stem.lower(),
                        "entry": entries[i],
                        "source": str(path),
                    },
                )
            )
    return docs


def make_pgvector_retriever(
    collection_name="support_docs", connection_string=None, search_kwargs=None
):
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    from langchain_postgres import PGVector

    connection_string = connection_string or os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError(
            "POSTGRES_CONNECTION_STRING is required for the live retriever"
        )
    if search_kwargs is not None and not isinstance(search_kwargs, dict):
        raise TypeError("search_kwargs must be a dictionary")
    embeddings = GoogleGenerativeAIEmbeddings(
        model=os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
    )
    return PGVector(
        embeddings=embeddings,
        collection_name=collection_name,
        connection=connection_string,
    ).as_retriever(search_kwargs=search_kwargs or {})

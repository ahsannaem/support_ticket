"""This module provides common utilities for the agent, including document loading and PGVector retriever creation.

    It handles loading and splitting documents, creating a PGVector retriever, and managing environment variables.
    
    """


import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain.schema import Document
from langchain_postgres.vectorstores import PGVector
from langchain_google_genai.embeddings import GoogleGenerativeAIEmbeddings

# Load environment variables
load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
POSTGRES_CONNECTION_STRING = os.getenv("POSTGRES_CONNECTION_STRING")

if not GOOGLE_API_KEY:
    raise EnvironmentError("Missing GOOGLE_API_KEY in environment variables.")
if not POSTGRES_CONNECTION_STRING:
    raise EnvironmentError("Missing POSTGRES_CONNECTION_STRING in environment variables.")

def load_and_split_documents(dataset_path: str) -> List[Document]:
    """
    Load documents from directory and split them by entries labeled 'Entry N:'.

    Args:
        dataset_path: Path to the dataset directory.

    Returns:
        List of split Document objects with metadata.
    """
    loader = DirectoryLoader(
        dataset_path,
        glob="**/*.txt",
        loader_cls=TextLoader
    )
    raw_docs = loader.load()
    split_docs = []

    for doc in raw_docs:
        source = doc.metadata.get("source", "")
        category = Path(source).stem.lower()
        full_text = doc.page_content

        # Split text by "Entry N:"
        entries = re.split(r"\bEntry\s+(\d+):", full_text)

        # Skip intro (index 0) and process entries
        for i in range(1, len(entries), 2):
            entry_num = entries[i]
            entry_text = entries[i + 1].strip()

            split_docs.append(
                Document(
                    page_content=entry_text,
                    metadata={
                        "category": category,
                        "entry": entry_num,
                        "source": source,
                    }
                )
            )
    return split_docs

def make_pgvector_retriever(
    collection_name: str = "support_docs",
    connection_string: Optional[str] = None,
    search_kwargs: Optional[Dict] = None
) -> PGVector:
    """
    Create and return a PGVector retriever instance.

    Args:
        collection_name: Name of the PGVector collection.
        connection_string: Postgres connection string (defaults to env variable).
        search_kwargs: Optional dictionary of search parameters.

    Returns:
        Configured PGVector retriever.
    """
    connection_string = connection_string or POSTGRES_CONNECTION_STRING
    if not connection_string:
        raise ValueError("Postgres connection string must be provided or set in environment.")

    search_kwargs = search_kwargs or {}

    if not isinstance(search_kwargs, dict):
        raise TypeError(f"Expected 'search_kwargs' to be a dict but got {type(search_kwargs).__name__}")

    embedding_model = GoogleGenerativeAIEmbeddings(model="models/embedding-001")

    try:
        vectorstore = PGVector.from_existing_index(
            embedding=embedding_model,
            collection_name=collection_name,
            connection=connection_string
        )
    except Exception as e:
        raise RuntimeError(f"Failed to initialize PGVector retriever: {e}")

    try:
        return vectorstore.as_retriever(search_kwargs=search_kwargs)
    except Exception as e:
        raise RuntimeError(f"Failed to get retriever from PGVector: {e}")
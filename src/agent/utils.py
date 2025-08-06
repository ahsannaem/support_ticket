"""
Manage the configuration of various retrievers and utilities.

This module provides functionality to create and manage LLMs and refresh RAG indexes.
"""

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.embeddings import GoogleGenerativeAIEmbeddings
from langchain_postgres.vectorstores import PGVector
from agent.common import load_and_split_documents, POSTGRES_CONNECTION_STRING, GOOGLE_API_KEY

def get_llm() -> ChatGoogleGenerativeAI:
    """Factory method to return a new LLM instance per request."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        google_api_key=GOOGLE_API_KEY
    )

def refresh_rag(dataset_path: str = "static/dataset"):
    """
    Loads documents, splits them, and refreshes the PGVector index.
    """
    docs = load_and_split_documents(dataset_path)
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    PGVector.from_documents(
        documents=docs,
        embedding=embeddings,
        collection_name="support_docs",
        connection=POSTGRES_CONNECTION_STRING,
    )
    print("RAG documents loaded and indexed successfully.")
"""Compatibility imports; retrieval now has one implementation in common."""

from agent.common import load_and_split_documents, make_pgvector_retriever

__all__ = ["load_and_split_documents", "make_pgvector_retriever"]

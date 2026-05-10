"""RAG tools: rag_ingest, rag_search, rag_stats, rag_clear."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BaseTool

if TYPE_CHECKING:
    from ..rag import RAGSystem


class RAGIngestTool(BaseTool):
    name = "rag_ingest"
    description = (
        "Ingest a file or directory into the local knowledge base for semantic search. "
        "Supports .txt, .md, .py, .pdf, .docx, .csv, .xlsx, .json, .yaml and most code files. "
        "Use this before rag_search when working with large documents."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to a file or directory to ingest.",
            },
            "chunk_size": {
                "type": "integer",
                "description": "Words per chunk (default 500).",
            },
        },
        "required": ["path"],
    }

    def __init__(self, rag: "RAGSystem"):
        self._rag = rag

    def execute(self, path: str, chunk_size: int = 500) -> str:
        result = self._rag.ingest(path, chunk_size=chunk_size)
        if "error" in result:
            return f"Error: {result['error']}"
        return (
            f"Ingested {result['files']} file(s) → {result['chunks']} chunks added to knowledge base."
            + (f" ({result['skipped']} file(s) skipped)" if result["skipped"] else "")
        )


class RAGSearchTool(BaseTool):
    name = "rag_search"
    description = (
        "Search the local knowledge base using semantic similarity. "
        "Returns the most relevant document chunks for the query. "
        "Use after rag_ingest to retrieve context from large documents."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query.",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (default 5).",
            },
        },
        "required": ["query"],
    }

    def __init__(self, rag: "RAGSystem"):
        self._rag = rag

    def execute(self, query: str, top_k: int = 5) -> str:
        results = self._rag.search(query, top_k=top_k)
        if not results:
            return "No results found in knowledge base. Use rag_ingest to add documents first."
        lines = [
            f"{i + 1}. [score={r['score']:.3f}] {r['source']}\n   {r['text'][:300].strip()}"
            for i, r in enumerate(results)
        ]
        return f"Found {len(results)} result(s):\n\n" + "\n\n".join(lines)


class RAGStatsTool(BaseTool):
    name = "rag_stats"
    description = "Show the current state of the local knowledge base (chunk count, backend, embed model)."
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, rag: "RAGSystem"):
        self._rag = rag

    def execute(self) -> str:
        s = self._rag.stats()
        lines = [
            f"Backend:       {s['backend']}",
            f"Chunks stored: {s['document_chunks']}",
            f"Embed model:   {s['embed_model']} ({s['embed_backend']})",
            f"Embed active:  {s['embed_available']}",
            f"Persist dir:   {s['persist_dir']}",
        ]
        return "\n".join(lines)


class RAGClearTool(BaseTool):
    name = "rag_clear"
    description = "Clear the entire local knowledge base. All ingested documents will be removed."
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, rag: "RAGSystem"):
        self._rag = rag

    def execute(self) -> str:
        before = self._rag.count
        self._rag.clear()
        return f"Knowledge base cleared ({before} chunks removed)."

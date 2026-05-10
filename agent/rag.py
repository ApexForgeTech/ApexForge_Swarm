"""
RAG (Retrieval-Augmented Generation) system for ApexForge Swarm.

Primary:  ChromaDB + nomic-embed-text (via Ollama)
Fallback: JSON persist store + TF-IDF keyword search (no external deps)
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import RAGConfig

logger = logging.getLogger("rag")
logger.addHandler(logging.NullHandler())


# ── Text extraction ──────────────────────────────────────────────────────────

_TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".yaml", ".yml", ".toml", ".json", ".sh", ".bash", ".zsh",
    ".html", ".css", ".sql", ".go", ".rs", ".java", ".c", ".cpp",
    ".h", ".hpp", ".rb", ".php", ".swift", ".kt", ".r", ".m",
}


def _extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _TEXT_EXTENSIONS:
        return path.read_text(encoding="utf-8", errors="replace")
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext == ".csv":
        return path.read_text(encoding="utf-8", errors="replace")
    if ext in {".xlsx", ".xls"}:
        return _extract_xlsx(path)
    # Best-effort for unknown types
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _extract_pdf(path: Path) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        return path.read_bytes().decode("latin-1", errors="ignore")
    except Exception:
        return ""


def _extract_docx(path: Path) -> str:
    try:
        from zipfile import ZipFile
        from xml.etree import ElementTree as ET
        with ZipFile(path) as zf:
            data = zf.read("word/document.xml")
        root = ET.fromstring(data)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        return "\n".join(node.text for node in root.findall(".//w:t", ns) if node.text)
    except Exception:
        return ""


def _extract_xlsx(path: Path) -> str:
    try:
        import pandas as pd
        dfs = pd.read_excel(str(path), sheet_name=None)
        parts = []
        for sheet, df in dfs.items():
            parts.append(f"# Sheet: {sheet}\n{df.to_csv(index=False)}")
        return "\n\n".join(parts)
    except Exception:
        return ""


# ── Chunking ─────────────────────────────────────────────────────────────────

def _split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        if len(chunk.strip()) > 40:
            chunks.append(chunk)
        start += max(chunk_size - overlap, 1)
    return chunks


# ── TF-IDF keyword fallback ───────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-ZğüşıöçĞÜŞİÖÇ]{2,}", text.lower())


def _tfidf_score(query_tokens: list[str], doc_tokens: list[str], corpus_df: Counter, n_docs: int) -> float:
    if not doc_tokens:
        return 0.0
    doc_tf = Counter(doc_tokens)
    score = 0.0
    for tok in set(query_tokens):
        tf = doc_tf.get(tok, 0) / len(doc_tokens)
        df = corpus_df.get(tok, 0)
        idf = math.log((n_docs + 1) / (df + 1)) + 1.0
        score += tf * idf
    return score


# ── Simple JSON fallback store ────────────────────────────────────────────────

class _SimpleStore:
    """
    Fallback when chromadb is not installed.
    Persists documents as JSON; search uses TF-IDF keyword matching.
    """

    def __init__(self, persist_dir: Path):
        self._path = persist_dir / "simple_store.json"
        self._lock = threading.Lock()
        self._data: list[dict[str, Any]] = []
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                self._data = []

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, doc_id: str, text: str, metadata: dict) -> None:
        with self._lock:
            for item in self._data:
                if item["id"] == doc_id:
                    item["text"] = text
                    item["metadata"] = metadata
                    self._save()
                    return
            self._data.append({"id": doc_id, "text": text, "metadata": metadata})
            self._save()

    def query(self, query: str, top_k: int = 5) -> list[dict]:
        with self._lock:
            if not self._data:
                return []
            query_tokens = _tokenize(query)
            corpus_df: Counter = Counter()
            tokenized = []
            for item in self._data:
                toks = _tokenize(item["text"])
                tokenized.append(toks)
                for tok in set(toks):
                    corpus_df[tok] += 1
            n_docs = len(self._data)
            scored = []
            for item, toks in zip(self._data, tokenized):
                score = _tfidf_score(query_tokens, toks, corpus_df, n_docs)
                scored.append((score, item))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                {"text": item["text"], "source": item["metadata"].get("source", ""), "score": round(score, 4)}
                for score, item in scored[:top_k]
                if score > 0
            ]

    def count(self) -> int:
        with self._lock:
            return len(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data = []
            self._save()

    @property
    def backend_name(self) -> str:
        return "simple_json"


# ── ChromaDB store ────────────────────────────────────────────────────────────

class _ChromaStore:
    """ChromaDB-backed vector store."""

    def __init__(self, persist_dir: Path, collection_name: str = "apexforge_swarm"):
        import chromadb
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._col = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, doc_id: str, text: str, metadata: dict, embedding: list[float] | None = None) -> None:
        kwargs: dict[str, Any] = dict(
            documents=[text],
            ids=[doc_id],
            metadatas=[metadata],
        )
        if embedding:
            kwargs["embeddings"] = [embedding]
        self._col.upsert(**kwargs)

    def query(self, query: str, top_k: int = 5, query_embedding: list[float] | None = None) -> list[dict]:
        if self._col.count() == 0:
            return []
        k = min(top_k, self._col.count())
        if query_embedding:
            results = self._col.query(
                query_embeddings=[query_embedding],
                n_results=k,
                include=["documents", "metadatas", "distances"],
            )
        else:
            results = self._col.query(
                query_texts=[query],
                n_results=k,
                include=["documents", "metadatas", "distances"],
            )
        items = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            items.append({
                "text": doc,
                "source": meta.get("source", ""),
                "score": round(max(0.0, 1.0 - dist), 4),
            })
        return items

    def count(self) -> int:
        return self._col.count()

    def clear(self) -> None:
        name = self._col.name
        self._client.delete_collection(name)
        self._col = self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def backend_name(self) -> str:
        return "chromadb"


# ── Embedding ─────────────────────────────────────────────────────────────────

def _embed_ollama(texts: list[str], host: str, model: str) -> list[list[float]]:
    """Embed texts using Ollama's /api/embeddings endpoint."""
    from urllib.request import urlopen, Request as UReq
    embeddings = []
    for text in texts:
        payload = json.dumps({"model": model, "prompt": text}).encode()
        req = UReq(
            f"{host.rstrip('/')}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        embeddings.append(data["embedding"])
    return embeddings


def _embed_openai_compat(texts: list[str], base_url: str, api_key: str, model: str) -> list[list[float]]:
    """Embed texts using OpenAI-compatible /v1/embeddings endpoint."""
    try:
        import openai
        client = openai.OpenAI(api_key=api_key, base_url=base_url or None)
        resp = client.embeddings.create(input=texts, model=model)
        return [item.embedding for item in resp.data]
    except Exception:
        from urllib.request import urlopen, Request as UReq
        url = f"{base_url.rstrip('/')}/embeddings"
        payload = json.dumps({"input": texts, "model": model}).encode()
        req = UReq(url, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        })
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return [item["embedding"] for item in data["data"]]


# ── Main RAGSystem ─────────────────────────────────────────────────────────────

class RAGSystem:
    """
    Local-first RAG system.

    Backends:
      - chromadb + Ollama/OpenAI embeddings (preferred)
      - JSON store + TF-IDF keyword search (fallback)
    """

    def __init__(self, config: "RAGConfig", ollama_host: str = "http://localhost:11434"):
        self._config = config
        self._ollama_host = ollama_host
        persist_dir = Path(config.persist_dir)
        persist_dir.mkdir(parents=True, exist_ok=True)

        self._store: _ChromaStore | _SimpleStore
        try:
            self._store = _ChromaStore(persist_dir)
            logger.info("rag_backend_chromadb", extra={"persist_dir": str(persist_dir)})
        except ImportError:
            self._store = _SimpleStore(persist_dir)
            logger.warning("rag_backend_simple_json_chromadb_missing")

        self._embed_available: bool | None = None  # lazily detected

    # ── Embedding ─────────────────────────────────────────────────────────

    def _get_embeddings(self, texts: list[str]) -> list[list[float]] | None:
        if self._embed_available is False:
            return None
        cfg = self._config
        try:
            if cfg.embed_backend == "openai_compat":
                from .config import Config  # avoid circular at module level
                embs = _embed_openai_compat(texts, cfg.embed_base_url, cfg.embed_api_key, cfg.embed_model)
            else:
                embs = _embed_ollama(texts, self._ollama_host, cfg.embed_model)
            self._embed_available = True
            return embs
        except Exception as exc:
            if self._embed_available is None:
                logger.warning("rag_embed_unavailable", extra={"error": str(exc)})
            self._embed_available = False
            return None

    # ── Ingest ────────────────────────────────────────────────────────────

    def ingest(self, source: str | Path, *, chunk_size: int | None = None, overlap: int | None = None) -> dict[str, Any]:
        """
        Ingest a file or directory into the knowledge base.
        Returns {"chunks": N, "files": M, "skipped": K}.
        """
        path = Path(source)
        cs = chunk_size or self._config.chunk_size
        ov = overlap or self._config.chunk_overlap

        files: list[Path] = []
        if path.is_dir():
            for ext in list(_TEXT_EXTENSIONS) + [".pdf", ".docx", ".csv", ".xlsx"]:
                files.extend(path.rglob(f"*{ext}"))
        elif path.exists():
            files = [path]
        else:
            return {"error": f"Path not found: {source}", "chunks": 0, "files": 0, "skipped": 0}

        total_chunks = 0
        skipped = 0
        for file in files:
            try:
                text = _extract_text(file)
                if not text.strip():
                    skipped += 1
                    continue
                chunks = _split_text(text, cs, ov)
                embeddings = self._get_embeddings(chunks)
                for i, chunk in enumerate(chunks):
                    doc_id = f"{file.name}_{hashlib.md5(chunk.encode()).hexdigest()[:10]}"
                    metadata = {"source": str(file), "chunk_index": i, "total_chunks": len(chunks)}
                    if isinstance(self._store, _ChromaStore):
                        emb = embeddings[i] if embeddings else None
                        self._store.upsert(doc_id, chunk, metadata, embedding=emb)
                    else:
                        self._store.upsert(doc_id, chunk, metadata)
                total_chunks += len(chunks)
                logger.debug("rag_ingested", extra={"file": str(file), "chunks": len(chunks)})
            except Exception as exc:
                logger.warning("rag_ingest_error", extra={"file": str(file), "error": str(exc)})
                skipped += 1

        return {"chunks": total_chunks, "files": len(files) - skipped, "skipped": skipped}

    # ── Search ────────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """Return top-k relevant chunks for the query."""
        k = top_k or self._config.top_k
        if isinstance(self._store, _ChromaStore):
            embs = self._get_embeddings([query])
            query_emb = embs[0] if embs else None
            return self._store.query(query, top_k=k, query_embedding=query_emb)
        return self._store.query(query, top_k=k)

    def build_context(self, query: str, top_k: int | None = None) -> str:
        """Build a formatted context block for injection into the agent prompt."""
        results = self.search(query, top_k)
        if not results:
            return ""
        parts = [
            f"[{i + 1}] source={r['source']} score={r['score']}\n{r['text']}"
            for i, r in enumerate(results)
        ]
        return "## Relevant Knowledge (RAG)\n\n" + "\n\n---\n\n".join(parts)

    # ── Stats & management ────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "backend": self._store.backend_name,
            "document_chunks": self._store.count(),
            "embed_model": self._config.embed_model,
            "embed_backend": self._config.embed_backend,
            "embed_available": self._embed_available,
            "persist_dir": str(self._config.persist_dir),
        }

    def clear(self) -> None:
        self._store.clear()
        self._embed_available = None

    @property
    def available(self) -> bool:
        return True

    @property
    def count(self) -> int:
        return self._store.count()

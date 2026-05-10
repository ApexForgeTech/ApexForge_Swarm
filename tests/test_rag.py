"""Tests for agent/rag.py — works without chromadb or Ollama installed."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.config import RAGConfig
from agent.rag import (
    RAGSystem,
    _SimpleStore,
    _split_text,
    _extract_text,
    _tokenize,
    _tfidf_score,
)
from collections import Counter


# ── Unit: chunking ────────────────────────────────────────────────────────────

class ChunkingTests(unittest.TestCase):
    def test_split_basic(self):
        words = ["word"] * 600
        text = " ".join(words)
        chunks = _split_text(text, chunk_size=500, overlap=50)
        self.assertGreaterEqual(len(chunks), 2)
        for chunk in chunks:
            self.assertGreater(len(chunk.strip()), 40)

    def test_split_short_text_single_chunk(self):
        text = "Short document with enough words to form one chunk that passes the minimum length check."
        chunks = _split_text(text, chunk_size=500, overlap=50)
        self.assertEqual(len(chunks), 1)

    def test_split_empty_text(self):
        self.assertEqual(_split_text(""), [])

    def test_split_overlap_produces_extra_chunks(self):
        words = ["w"] * 200
        text = " ".join(words)
        chunks_no_overlap = _split_text(text, chunk_size=100, overlap=0)
        chunks_with_overlap = _split_text(text, chunk_size=100, overlap=50)
        self.assertGreater(len(chunks_with_overlap), len(chunks_no_overlap))


# ── Unit: TF-IDF ──────────────────────────────────────────────────────────────

class TfIdfTests(unittest.TestCase):
    def test_tokenize_basic(self):
        tokens = _tokenize("Hello World foo bar")
        self.assertIn("hello", tokens)
        self.assertIn("world", tokens)

    def test_tokenize_strips_short_words(self):
        tokens = _tokenize("I am a cat")
        self.assertNotIn("i", tokens)
        self.assertNotIn("a", tokens)

    def test_tfidf_score_matching_doc_higher(self):
        query = _tokenize("python programming")
        doc_match = _tokenize("python programming language tutorial")
        doc_unrelated = _tokenize("cooking recipe food pasta sauce")
        corpus_df = Counter(doc_match + doc_unrelated)
        n_docs = 2
        score_match = _tfidf_score(query, doc_match, corpus_df, n_docs)
        score_unrelated = _tfidf_score(query, doc_unrelated, corpus_df, n_docs)
        self.assertGreater(score_match, score_unrelated)

    def test_tfidf_score_empty_doc(self):
        score = _tfidf_score(["python"], [], Counter(), 1)
        self.assertEqual(score, 0.0)


# ── Unit: text extraction ─────────────────────────────────────────────────────

class TextExtractionTests(unittest.TestCase):
    def test_extract_txt_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write("Hello from a text file.")
            path = Path(f.name)
        try:
            text = _extract_text(path)
            self.assertIn("Hello", text)
        finally:
            path.unlink(missing_ok=True)

    def test_extract_py_file(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write("def hello(): return 'world'")
            path = Path(f.name)
        try:
            text = _extract_text(path)
            self.assertIn("hello", text)
        finally:
            path.unlink(missing_ok=True)

    def test_extract_md_file(self):
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, encoding="utf-8") as f:
            f.write("# Title\n\nSome markdown content here.")
            path = Path(f.name)
        try:
            text = _extract_text(path)
            self.assertIn("Title", text)
        finally:
            path.unlink(missing_ok=True)


# ── Unit: SimpleStore ─────────────────────────────────────────────────────────

class SimpleStoreTests(unittest.TestCase):
    def _store(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        return _SimpleStore(Path(tmpdir.name))

    def test_upsert_and_count(self):
        store = self._store()
        store.upsert("doc-1", "python programming tutorial", {"source": "a.txt"})
        store.upsert("doc-2", "cooking pasta recipe italian", {"source": "b.txt"})
        self.assertEqual(store.count(), 2)

    def test_upsert_replaces_existing(self):
        store = self._store()
        store.upsert("doc-1", "original content here", {"source": "x.txt"})
        store.upsert("doc-1", "updated content here different", {"source": "x.txt"})
        self.assertEqual(store.count(), 1)

    def test_query_returns_relevant_first(self):
        store = self._store()
        store.upsert("doc-1", "python programming language tutorial guide", {"source": "py.txt"})
        store.upsert("doc-2", "cooking recipe pasta sauce tomato garlic", {"source": "cook.txt"})
        store.upsert("doc-3", "javascript frontend web development tutorial", {"source": "js.txt"})
        results = store.query("python programming", top_k=3)
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["source"], "py.txt")

    def test_query_empty_store(self):
        store = self._store()
        results = store.query("anything")
        self.assertEqual(results, [])

    def test_clear_removes_all(self):
        store = self._store()
        store.upsert("doc-1", "some content here", {"source": "x.txt"})
        store.clear()
        self.assertEqual(store.count(), 0)

    def test_persistence_survives_reload(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        store1 = _SimpleStore(Path(tmpdir.name))
        store1.upsert("doc-1", "persistent content here test", {"source": "p.txt"})
        store2 = _SimpleStore(Path(tmpdir.name))
        self.assertEqual(store2.count(), 1)

    def test_backend_name(self):
        store = self._store()
        self.assertEqual(store.backend_name, "simple_json")


# ── Integration: RAGSystem (no chromadb, no Ollama) ──────────────────────────

class RAGSystemTests(unittest.TestCase):
    def _rag(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        cfg = RAGConfig(persist_dir=tmpdir.name, enabled=True, top_k=3)
        # Force simple store (no chromadb)
        with mock.patch("agent.rag._ChromaStore", side_effect=ImportError("no chromadb")):
            rag = RAGSystem(cfg, ollama_host="http://localhost:11434")
        return rag

    def test_ingest_text_file(self):
        rag = self._rag()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write(" ".join(["python"] * 100 + ["programming"] * 100 + ["tutorial"] * 100))
            path = Path(f.name)
        try:
            result = rag.ingest(str(path))
            self.assertGreater(result["chunks"], 0)
            self.assertEqual(result["files"], 1)
            self.assertEqual(result["skipped"], 0)
        finally:
            path.unlink(missing_ok=True)

    def test_ingest_nonexistent_path(self):
        rag = self._rag()
        result = rag.ingest("/nonexistent/path/file.txt")
        self.assertIn("error", result)
        self.assertEqual(result["chunks"], 0)

    def test_search_after_ingest(self):
        rag = self._rag()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write(" ".join(["authentication", "security", "password", "hash", "jwt"] * 60))
            auth_path = Path(f.name)
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write(" ".join(["database", "sql", "query", "table", "index", "postgres"] * 60))
            db_path = Path(f.name)
        try:
            rag.ingest(str(auth_path))
            rag.ingest(str(db_path))
            results = rag.search("authentication password security", top_k=3)
            self.assertGreater(len(results), 0)
            top_source = results[0]["source"]
            self.assertEqual(top_source, str(auth_path))
        finally:
            auth_path.unlink(missing_ok=True)
            db_path.unlink(missing_ok=True)

    def test_search_empty_store(self):
        rag = self._rag()
        results = rag.search("anything")
        self.assertEqual(results, [])

    def test_build_context_returns_formatted_string(self):
        rag = self._rag()
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, encoding="utf-8") as f:
            f.write(" ".join(["docker", "container", "image", "kubernetes", "deployment"] * 60))
            path = Path(f.name)
        try:
            rag.ingest(str(path))
            ctx = rag.build_context("docker container deployment", top_k=2)
            self.assertIn("## Relevant Knowledge (RAG)", ctx)
            self.assertIn("score=", ctx)
        finally:
            path.unlink(missing_ok=True)

    def test_build_context_empty_store(self):
        rag = self._rag()
        self.assertEqual(rag.build_context("anything"), "")

    def test_stats_structure(self):
        rag = self._rag()
        stats = rag.stats()
        self.assertIn("backend", stats)
        self.assertIn("document_chunks", stats)
        self.assertIn("embed_model", stats)
        self.assertIn("embed_backend", stats)
        self.assertIn("persist_dir", stats)
        self.assertEqual(stats["backend"], "simple_json")

    def test_clear_resets_count(self):
        rag = self._rag()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write(" ".join(["word"] * 200))
            path = Path(f.name)
        try:
            rag.ingest(str(path))
            self.assertGreater(rag.count, 0)
            rag.clear()
            self.assertEqual(rag.count, 0)
        finally:
            path.unlink(missing_ok=True)

    def test_ingest_directory(self):
        rag = self._rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, topic in enumerate(["python tutorial guide", "javascript frontend web", "database sql query"]):
                (Path(tmpdir) / f"doc{i}.txt").write_text(" ".join([w for w in topic.split()] * 80), encoding="utf-8")
            result = rag.ingest(tmpdir)
            self.assertEqual(result["files"], 3)
            self.assertGreater(result["chunks"], 0)

    def test_available_property(self):
        rag = self._rag()
        self.assertTrue(rag.available)


# ── Integration: RAG tools ────────────────────────────────────────────────────

class RAGToolsTests(unittest.TestCase):
    def _rag(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        cfg = RAGConfig(persist_dir=tmpdir.name, enabled=True, top_k=3)
        with mock.patch("agent.rag._ChromaStore", side_effect=ImportError("no chromadb")):
            return RAGSystem(cfg)

    def test_ingest_tool_success(self):
        from agent.tools.rag_tools import RAGIngestTool
        rag = self._rag()
        tool = RAGIngestTool(rag)
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write(" ".join(["word"] * 300))
            path = Path(f.name)
        try:
            result = tool.execute(path=str(path))
            self.assertIn("chunk", result)
        finally:
            path.unlink(missing_ok=True)

    def test_ingest_tool_bad_path(self):
        from agent.tools.rag_tools import RAGIngestTool
        rag = self._rag()
        tool = RAGIngestTool(rag)
        result = tool.execute(path="/nonexistent/file.txt")
        self.assertIn("Error", result)

    def test_search_tool_no_results(self):
        from agent.tools.rag_tools import RAGSearchTool
        rag = self._rag()
        tool = RAGSearchTool(rag)
        result = tool.execute(query="something")
        self.assertIn("rag_ingest", result)

    def test_stats_tool(self):
        from agent.tools.rag_tools import RAGStatsTool
        rag = self._rag()
        tool = RAGStatsTool(rag)
        result = tool.execute()
        self.assertIn("Backend", result)
        self.assertIn("Chunks stored", result)

    def test_clear_tool(self):
        from agent.tools.rag_tools import RAGClearTool, RAGIngestTool
        rag = self._rag()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write(" ".join(["word"] * 200))
            path = Path(f.name)
        try:
            RAGIngestTool(rag).execute(path=str(path))
            result = RAGClearTool(rag).execute()
            self.assertIn("cleared", result)
            self.assertEqual(rag.count, 0)
        finally:
            path.unlink(missing_ok=True)

# ApexForge Swarm — Implementation Plan
## From Working Prototype → Production-Grade Local AI Platform

> **Tarix:** 2026-05-10  
> **Məqsəd:** Mövcud sistemin kritik xətlərini düzəltmək, yeni xüsusiyyətlər əlavə etmək və platformu Ollama-nın həqiqi, daha güclü alternativinə çevirmək.

---

## Mövcud Vəziyyətin Xəritəsi

```
KRITIK PROBLEMLƏR          ORTA PROBLEMLƏR          ÇATIŞMAYAN XÜSUSİYYƏTLƏR
─────────────────          ───────────────          ─────────────────────────
max_tokens: 384 [!]        auth yoxdur              OpenAI-compat backend
llama.cpp streaming yox    session in-memory         RAG / Vector Search
token count kobud          error types zəif          Plugin sistemi
num_ctx çox az             test coverage az          Mission history
```

---

## Faza Xəritəsi (Ümumi Görünüş)

```
Həftə 1        Həftə 2        Həftə 3-4      Həftə 5-6      Həftə 7-8
───────────    ───────────    ───────────    ───────────    ───────────
FAZA 1         FAZA 2         FAZA 3         FAZA 4         FAZA 5
Kritik         Yeni           RAG +          Multi-Agent    Plugin +
Düzəlişlər    Backendlər     Güvenlik       Upgrade        Desktop
    │              │              │              │              │
    ▼              ▼              ▼              ▼              ▼
[İşləyir]     [Genişlənir]  [Güclənir]    [Ağıllanır]   [Bitir]
```

---

## FAZA 1 — Kritik Düzəlişlər
**Həftə 1 | Prioritet: BLOCKER**

Bu düzəlişlər olmadan sistem layiqli çalışmır.

### 1.1 — `max_tokens` Düzəlişi

**Problem:** `config.yaml`-da `max_tokens: 384` — bu çox azdır. Uzun cavablar kəsilir, agent yarımçıq işlər görür.

**Fayl:** `agent/config.py:89`, `config.yaml:32`

**Həll:**
```python
# agent/config.py
@dataclass
class LlamaCppConfig:
    max_tokens: int = 2048        # 384 → 2048
    num_ctx: int = 16384          # context window artırılır
    request_timeout: int = 600    # 300 → 600 (böyük modellər üçün)
```

```yaml
# config.yaml
llama_cpp:
  max_tokens: 2048
  request_timeout: 600
ollama:
  num_ctx: 16384
```

**Niyə:** 384 token = ~300 söz. Hər hansı real tapşırıq üçün yetərsizdir.

---

### 1.2 — llama.cpp Üçün Real Streaming

**Problem:** `llm_backend.py:724` — `"stream": False`. Bütün cavab hazır olana qədər gözləyir. İstifadəçi boş ekrana baxır.

**Fayl:** `agent/llm_backend.py:701-752`

**Həll — SSE streaming əlavə et:**
```python
# agent/llm_backend.py içərisindəki LlamaCppBackend.chat_stream()
def chat_stream(self, messages, tools=None):
    with self._request_slot():
        self.ensure_ready()
        
        # Tool varsa streaming olmur (OpenAI spec tələbi)
        use_streaming = not bool(tools)
        
        payload = {
            "model": self.config.ollama.model,
            "messages": self._normalize_messages(messages),
            "temperature": self.config.ollama.temperature,
            "max_tokens": self.config.llama_cpp.max_tokens,
            "stream": use_streaming,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = False

        if not use_streaming:
            # Tool calling path — köhnə metod
            response = self._request_json("POST", "/v1/chat/completions", payload)
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message", {})
            yield LLMChunk(
                content=message.get("content") or "",
                tool_calls=self._parse_tool_calls(message.get("tool_calls")),
            )
        else:
            # Real SSE streaming path
            yield from self._stream_sse(payload)

def _stream_sse(self, payload):
    """Server-Sent Events streaming üçün."""
    url = urljoin(self._base_url(), "/v1/chat/completions")
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.llama_cpp.api_key}",
            "Accept": "text/event-stream",
        },
    )
    with urlopen(req, timeout=self.config.llama_cpp.request_timeout) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            try:
                chunk = json.loads(body)
                delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                content = delta.get("content") or ""
                if content:
                    yield LLMChunk(content=content)
            except json.JSONDecodeError:
                continue
```

**Niyə:** İstifadəçi cavabı real-time görür. UX kəskin yaxşılaşır.

---

### 1.3 — Dəqiq Token Sayı

**Problem:** `agent/core.py:19` — `_CHARS_PER_TOKEN = 4` kobud təxmindir. Azərbaycan/Türk dili üçün yanlış ola bilər.

**Fayl:** `agent/core.py:19`, `agent/core.py:77-78`

**Həll:**
```python
# agent/core.py
def _token_estimate(self) -> int:
    """
    Daha dəqiq token təxmini.
    - ASCII mətn: ~4 char/token
    - Unicode/CJK/emoji: ~2 char/token  
    - Tool result JSON: ~3 char/token
    """
    total = 0
    for m in self.messages:
        content = str(m.get("content", ""))
        # Unicode ratio-ya görə çarpan seç
        unicode_ratio = sum(1 for c in content if ord(c) > 127) / max(len(content), 1)
        chars_per_tok = 4 - round(unicode_ratio * 2)  # 2-4 arası
        total += len(content) // max(chars_per_tok, 2)
        # Tool calls da sayılır
        if m.get("tool_calls"):
            total += len(json.dumps(m["tool_calls"])) // 3
    return total
```

---

### 1.4 — Strukturlaşdırılmış Error Tipləri

**Problem:** Hər yerdə `str(exc)` — debug üçün çox çətindir.

**Yeni fayl:** `agent/errors.py`

```python
# agent/errors.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class ApexError(Exception):
    message: str
    code: str
    provider: Optional[str] = None
    recoverable: bool = True

    def __str__(self):
        return f"[{self.code}] {self.message}"

class BackendError(ApexError):
    pass

class BackendNotReady(BackendError):
    pass

class BackendTimeout(BackendError):
    pass

class ToolError(ApexError):
    pass

class ConfigError(ApexError):
    recoverable: bool = False
```

---

## FAZA 2 — Yeni Backendlər
**Həftə 2 | Prioritet: YÜKSƏKKİ**

Ollama-dan daha güclü olmaq üçün daha çox backend lazımdır.

### 2.1 — OpenAI-Compatible Backend

Bu tək backend ilə bunlar dəstəklənir:
- GPT-4o, GPT-4 (OpenAI)
- Claude API (Anthropic) — `openai` compat mode
- Groq (ultra sürətli)
- Together.ai (open-source modellər)
- Mistral API
- Local OpenAI-compat serverlər (LM Studio, Jan.ai, vllm)

**Fayl:** `agent/llm_backend.py`-ə əlavə et

```python
class OpenAICompatBackend(BaseLLMBackend):
    """
    OpenAI Python SDK-dan istifadə edən universal backend.
    OpenAI, Groq, Together, Mistral, Anthropic compat — hamısı eyni interfeys.
    """

    def _client(self):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai paketi quraşdırılmayıb: pip install openai"
            ) from exc
        
        return OpenAI(
            api_key=self.config.openai_compat.api_key or "sk-placeholder",
            base_url=self.config.openai_compat.base_url or None,
        )

    def chat_stream(self, messages, tools=None):
        client = self._client()
        model = self.config.openai_compat.model or self.config.ollama.model
        
        kwargs = dict(
            model=model,
            messages=messages,
            temperature=self.config.ollama.temperature,
            max_tokens=self.config.openai_compat.max_tokens or 4096,
            stream=True,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
            kwargs["stream"] = False  # tool calling ilə streaming olmur

        if not tools:
            stream = client.chat.completions.create(**kwargs)
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield LLMChunk(content=delta.content)
        else:
            kwargs.pop("stream")
            resp = client.chat.completions.create(**kwargs, stream=False)
            msg = resp.choices[0].message
            tool_calls = []
            for tc in (msg.tool_calls or []):
                tool_calls.append(LLMToolCall(
                    id=tc.id,
                    function=LLMToolCallFunction(
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments or "{}"),
                    )
                ))
            yield LLMChunk(content=msg.content or "", tool_calls=tool_calls)

    def list_models(self) -> list[str]:
        try:
            client = self._client()
            return [m.id for m in client.models.list().data]
        except Exception:
            return [self.config.openai_compat.model or "gpt-4o"]

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            provider="openai_compat",
            multi_agent_supported=True,
            request_parallelism="parallel",
            mixed_model_missions="supported",
            auto_start_supported=False,
            local_model_discovery=False,
            notes=[
                "OpenAI, Groq, Together.ai, Mistral, LM Studio ilə işləyir.",
                "OPENAI_COMPAT_BASE_URL env ilə istənilən endpoint.",
            ],
        )
```

**Config əlavəsi:**
```python
# agent/config.py
@dataclass
class OpenAICompatConfig:
    base_url: str = ""           # boş = OpenAI rəsmi endpoint
    api_key: str = ""            # OPENAI_COMPAT_API_KEY
    model: str = "gpt-4o-mini"
    max_tokens: int = 4096

@dataclass
class Config:
    # ... mövcud fieldlər ...
    openai_compat: OpenAICompatConfig = field(default_factory=OpenAICompatConfig)
```

**Backend factory yenilənməsi:**
```python
def create_llm_backend(config) -> BaseLLMBackend:
    provider = (getattr(config.agent, "provider", "ollama") or "ollama").lower()
    backends = {
        "llama_cpp": LlamaCppBackend,
        "openai_compat": OpenAICompatBackend,
        "ollama": OllamaBackend,
    }
    cls = backends.get(provider, OllamaBackend)
    return cls(config)
```

**`.env.example`-ə əlavə:**
```env
# OpenAI / Groq / Together / Mistral / LM Studio
LLM_PROVIDER=openai_compat
OPENAI_COMPAT_API_KEY=sk-your-key
OPENAI_COMPAT_BASE_URL=                      # boş = OpenAI rəsmi
# OPENAI_COMPAT_BASE_URL=https://api.groq.com/openai/v1   # Groq
# OPENAI_COMPAT_BASE_URL=http://localhost:1234/v1          # LM Studio
OPENAI_COMPAT_MODEL=gpt-4o-mini
OPENAI_COMPAT_MAX_TOKENS=4096
```

---

### 2.2 — Backend Auto-Detection

**Fayl:** `agent/llm_backend.py`

```python
def detect_available_backends(config) -> list[str]:
    """Hansı backendlərin işlədiyini yoxlayır."""
    available = []
    
    # Ollama yoxla
    try:
        import ollama
        ollama.Client(host=config.ollama.host).list()
        available.append("ollama")
    except Exception:
        pass
    
    # llama.cpp yoxla
    try:
        url = config.llama_cpp.host.rstrip("/") + "/v1/models"
        urlopen(Request(url), timeout=3)
        available.append("llama_cpp")
    except Exception:
        pass
    
    # OpenAI compat yoxla
    if os.getenv("OPENAI_COMPAT_API_KEY") or os.getenv("OPENAI_API_KEY"):
        available.append("openai_compat")
    
    return available
```

---

## FAZA 3 — Güvenlik + Persistent Storage
**Həftə 3 | Prioritet: ORTA**

### 3.1 — Web API Authentication

**Problem:** `/api/config POST` endpoint-inə hər kəs daxil ola bilər.

**Fayl:** `agent/web/app.py`

```python
# agent/web/auth.py
import hashlib, secrets, os
from fastapi import Header, HTTPException

_API_KEY = os.getenv("APEXFORGE_API_KEY", "")

def require_auth(x_api_key: str = Header(default="")):
    if not _API_KEY:
        return  # auth deaktiv — local dev mode
    if not secrets.compare_digest(
        hashlib.sha256(x_api_key.encode()).digest(),
        hashlib.sha256(_API_KEY.encode()).digest()
    ):
        raise HTTPException(status_code=401, detail="Invalid API key")

# app.py-də:
from .auth import require_auth

@app.post("/api/config")
async def update_config(data: dict, _=Depends(require_auth)):
    ...
```

```env
# .env
APEXFORGE_API_KEY=your-secret-key-here   # boş = auth deaktiv (local dev)
```

---

### 3.2 — SQLite Session Storage

**Problem:** Server restart = bütün session history silinir.

**Yeni fayl:** `agent/session_store.py`

```python
# agent/session_store.py
import sqlite3, json, threading
from pathlib import Path
from typing import Any

class SessionStore:
    def __init__(self, db_path: Path):
        self._db = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    messages   TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS missions (
                    mission_id TEXT PRIMARY KEY,
                    prompt     TEXT NOT NULL,
                    result     TEXT,
                    events     TEXT DEFAULT '[]',
                    status     TEXT DEFAULT 'running',
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)

    def _conn(self):
        return sqlite3.connect(str(self._db))

    def save_session(self, session_id: str, messages: list[dict]):
        with self._lock:
            with self._conn() as conn:
                conn.execute("""
                    INSERT INTO sessions (session_id, messages, updated_at)
                    VALUES (?, ?, datetime('now'))
                    ON CONFLICT(session_id) DO UPDATE
                    SET messages=excluded.messages, updated_at=excluded.updated_at
                """, (session_id, json.dumps(messages, ensure_ascii=False)))

    def load_session(self, session_id: str) -> list[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT messages FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return json.loads(row[0]) if row else []

    def save_mission(self, mission_id: str, prompt: str, result: str, events: list, status: str = "completed"):
        with self._lock:
            with self._conn() as conn:
                conn.execute("""
                    INSERT INTO missions (mission_id, prompt, result, events, status)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(mission_id) DO UPDATE
                    SET result=excluded.result, events=excluded.events, status=excluded.status
                """, (mission_id, prompt, result, json.dumps(events, ensure_ascii=False), status))

    def list_missions(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT mission_id, prompt, status, created_at FROM missions ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [{"id": r[0], "prompt": r[1], "status": r[2], "created_at": r[3]} for r in rows]

    def get_mission(self, mission_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM missions WHERE mission_id = ?", (mission_id,)
            ).fetchone()
        if not row:
            return None
        cols = ["mission_id", "prompt", "result", "events", "status", "created_at"]
        data = dict(zip(cols, row))
        data["events"] = json.loads(data["events"])
        return data
```

**Web API-ə yeni endpoint-lər:**
```python
# agent/web/app.py
@app.get("/api/missions")
async def list_missions():
    return {"missions": _store.list_missions()}

@app.get("/api/missions/{mission_id}")
async def get_mission(mission_id: str):
    mission = _store.get_mission(mission_id)
    if not mission:
        raise HTTPException(404, "Mission not found")
    return mission
```

---

## FAZA 4 — RAG (Retrieval-Augmented Generation)
**Həftə 3-4 | Prioritet: YÜKSƏK**

Bu xüsusiyyət ApexForge Swarm-ı həqiqətən güclü edir. Model context-ə sığmayan böyük sənəd bazaları ilə işləyə bilir.

### 4.1 — Arxitektura

```
İstifadəçi sənədi yükləyir
         │
         ▼
  ┌─────────────┐
  │  Ingestion  │  ← PDF, DOCX, TXT, kodu parçalayır
  │  Pipeline   │
  └──────┬──────┘
         │ chunks
         ▼
  ┌─────────────┐
  │  Embedding  │  ← nomic-embed-text (local) və ya OpenAI embeddings
  │  Model      │
  └──────┬──────┘
         │ vectors
         ▼
  ┌─────────────┐
  │  ChromaDB   │  ← local vector store, persistent
  │  / FAISS    │
  └──────┬──────┘
         │
         │ Sorğu zamanı
         ▼
  ┌─────────────┐
  │  Semantic   │  ← top-k ən oxşar chunk-ları tap
  │  Search     │
  └──────┬──────┘
         │ relevant context
         ▼
  ┌─────────────┐
  │  Agent      │  ← context-i prompt-a əlavə et
  │  Context    │
  └─────────────┘
```

### 4.2 — İmplementasiya

**Yeni fayl:** `agent/rag.py`

```python
# agent/rag.py
import hashlib
from pathlib import Path
from typing import Any

class RAGSystem:
    """
    Local-first RAG. ChromaDB + nomic-embed-text (Ollama üzərindən).
    """

    def __init__(self, persist_dir: Path, ollama_host: str = "http://localhost:11434"):
        self._dir = persist_dir
        self._ollama_host = ollama_host
        self._collection = None
        self._init()

    def _init(self):
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(self._dir))
            self._collection = client.get_or_create_collection(
                name="apexforge_knowledge",
                metadata={"hnsw:space": "cosine"},
            )
        except ImportError:
            self._collection = None

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """nomic-embed-text via Ollama."""
        from urllib.request import urlopen, Request
        import json
        embeddings = []
        for text in texts:
            payload = json.dumps({"model": "nomic-embed-text", "prompt": text}).encode()
            req = Request(
                f"{self._ollama_host}/api/embeddings",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            embeddings.append(data["embedding"])
        return embeddings

    def ingest(self, source: str | Path, *, chunk_size: int = 500, overlap: int = 50) -> int:
        """Sənədi chunk-lara bölür və vector store-a əlavə edir."""
        if self._collection is None:
            return 0

        path = Path(source)
        text = self._extract_text(path)
        chunks = self._split(text, chunk_size, overlap)
        if not chunks:
            return 0

        embeddings = self._embed(chunks)
        ids = [f"{path.name}_{hashlib.md5(c.encode()).hexdigest()[:8]}" for c in chunks]
        metadatas = [{"source": str(path), "chunk": i} for i in range(len(chunks))]

        self._collection.upsert(
            documents=chunks,
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas,
        )
        return len(chunks)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Sorğuya ən uyğun chunk-ları tap."""
        if self._collection is None or self._collection.count() == 0:
            return []

        query_emb = self._embed([query])[0]
        results = self._collection.query(
            query_embeddings=[query_emb],
            n_results=min(top_k, self._collection.count()),
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
                "score": round(1 - dist, 4),
            })
        return items

    def build_context(self, query: str, top_k: int = 5) -> str:
        """Agent prompt-u üçün RAG context."""
        results = self.search(query, top_k)
        if not results:
            return ""
        parts = [f"[{i+1}] ({r['source']}, score={r['score']})\n{r['text']}"
                 for i, r in enumerate(results)]
        return "## Relevant Knowledge\n\n" + "\n\n---\n\n".join(parts)

    def _extract_text(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext in {".txt", ".md", ".py", ".js", ".ts", ".yaml", ".json"}:
            return path.read_text(encoding="utf-8", errors="replace")
        elif ext == ".pdf":
            return self._extract_pdf(path)
        elif ext == ".docx":
            return self._extract_docx(path)
        return path.read_text(encoding="utf-8", errors="replace")

    def _extract_pdf(self, path: Path) -> str:
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            return path.read_bytes().decode("latin-1", errors="ignore")

    def _extract_docx(self, path: Path) -> str:
        from zipfile import ZipFile
        from xml.etree import ElementTree as ET
        with ZipFile(path) as zf:
            data = zf.read("word/document.xml")
        root = ET.fromstring(data)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        return "\n".join(node.text for node in root.findall(".//w:t", ns) if node.text)

    def _split(self, text: str, size: int, overlap: int) -> list[str]:
        words = text.split()
        chunks, start = [], 0
        while start < len(words):
            end = start + size
            chunks.append(" ".join(words[start:end]))
            start += size - overlap
        return [c for c in chunks if len(c.strip()) > 50]

    @property
    def available(self) -> bool:
        return self._collection is not None

    def count(self) -> int:
        return self._collection.count() if self._collection else 0
```

**Tool kimi əlavə et:**
```python
# agent/tools/rag_tool.py
class RAGIngestTool(BaseTool):
    name = "rag_ingest"
    description = "Sənədi bilgi bazasına əlavə et (RAG)"

    def execute(self, file_path: str) -> str:
        count = self.rag.ingest(file_path)
        return f"✓ {file_path} — {count} chunk indeksləşdirildi."

class RAGSearchTool(BaseTool):
    name = "rag_search"
    description = "Bilgi bazasından semantik axtarış"

    def execute(self, query: str, top_k: int = 5) -> str:
        results = self.rag.search(query, top_k)
        if not results:
            return "Bilgi bazasında nəticə tapılmadı."
        lines = [f"{i+1}. [{r['score']:.3f}] {r['source']}\n   {r['text'][:200]}"
                 for i, r in enumerate(results)]
        return "\n\n".join(lines)
```

**requirements.txt-ə əlavə:**
```
chromadb>=0.5.0
pypdf>=4.0.0
openai>=1.0.0       # OpenAI compat backend üçün
```

---

## FAZA 5 — Multi-Agent Upgrade
**Həftə 4-5 | Prioritet: ORTA-YÜKSƏK**

### 5.1 — Mission Templates

Hər dəfə yeni mission qurmaq əvəzinə hazır şablonlar:

**Yeni fayl:** `agent/mission_templates.py`

```python
# agent/mission_templates.py
TEMPLATES = {
    "code_review": {
        "supervisor": {"role": "Senior Code Reviewer"},
        "workers": [
            {"role": "Security Analyst — security vulnerabilities, auth issues, injection risks"},
            {"role": "Architecture Reviewer — structure, coupling, design patterns"},
            {"role": "Test Coverage Analyst — missing tests, test quality"},
        ],
        "hint": "Kodu tam oxu, kritik problemləri sırala, düzəliş təklifləri ver.",
    },
    "research": {
        "supervisor": {"role": "Research Lead"},
        "workers": [
            {"role": "Web Researcher — current information, sources, links"},
            {"role": "Analyst — synthesis, patterns, conclusions"},
            {"role": "Fact Checker — verify claims, flag contradictions"},
        ],
        "hint": "Mövzunu araşdır, mənbələri yoxla, nəticəni strukturlaşdır.",
    },
    "repo_audit": {
        "supervisor": {"role": "Project Architect"},
        "workers": [
            {"role": "Codebase Explorer — file structure, module boundaries, dependencies"},
            {"role": "Risk Analyst — technical debt, anti-patterns, hidden bugs"},
            {"role": "Improvement Planner — specific, actionable improvements"},
        ],
        "hint": "Layihəni tam analiz et, prioritetləndirilmiş plan yaz.",
    },
    "document_processing": {
        "supervisor": {"role": "Document Analyst"},
        "workers": [
            {"role": "Content Extractor — key facts, figures, dates"},
            {"role": "Summarizer — concise summary for different audiences"},
            {"role": "Action Item Extractor — tasks, decisions, follow-ups"},
        ],
        "hint": "Sənədi tam oxu, hər worker öz payına fokuslan.",
    },
}

def get_template(name: str) -> dict | None:
    return TEMPLATES.get(name)

def list_templates() -> list[str]:
    return list(TEMPLATES.keys())
```

### 5.2 — Daha Güclü Worker Report Formatı

**Fayl:** `agent/reporting.py` genişləndirilməsi

```python
# agent/reporting.py əlavəsi
@dataclass
class EnhancedWorkerReport:
    worker_name: str
    role: str
    summary: str
    findings: list[str]
    completed_actions: list[str]
    evidence: list[str]
    open_questions: list[str]
    confidence: float        # 0.0 - 1.0
    tool_calls_made: int
    duration_seconds: float
    raw_output: str

    def quality_score(self) -> float:
        """Report keyfiyyətini ölç."""
        score = 0.0
        if self.findings:
            score += min(len(self.findings) * 0.1, 0.3)
        if self.completed_actions:
            score += min(len(self.completed_actions) * 0.1, 0.3)
        if self.evidence:
            score += min(len(self.evidence) * 0.1, 0.2)
        if self.tool_calls_made > 0:
            score += 0.2  # tool işlədib = real iş gördü
        return round(min(score, 1.0), 2)
```

### 5.3 — Agent-to-Agent Mesajlaşma

Workers bir-biri ilə məlumat paylaşa bilsin:

```python
# agent/multi_agent.py-ə əlavə
class MessageBus:
    """Workers arasında asynchronous mesajlaşma."""

    def __init__(self):
        self._messages: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    def send(self, from_agent: str, to_agent: str, message: str):
        with self._lock:
            if to_agent not in self._messages:
                self._messages[to_agent] = []
            self._messages[to_agent].append({
                "from": from_agent,
                "message": message,
                "ts": time.time(),
            })

    def receive(self, agent_name: str) -> list[dict]:
        with self._lock:
            msgs = self._messages.pop(agent_name, [])
        return msgs

    def broadcast(self, from_agent: str, message: str, exclude: list[str] = None):
        """Bütün agentlərə mesaj göndər."""
        # MultiAgentSystem-dən worker adları alınır
        pass
```

---

## FAZA 6 — Plugin / Tool Sistemi
**Həftə 6 | Prioritet: ORTA**

### 6.1 — Dynamic Tool Loading

**Yeni fayl:** `agent/plugin_loader.py`

```python
# agent/plugin_loader.py
import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Agent

def load_plugins(agent: "Agent", plugins_dir: Path):
    """plugins/ qovluğundakı tool-ları dynamic yüklə."""
    if not plugins_dir.exists():
        return

    for py_file in sorted(plugins_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for name in dir(module):
                obj = getattr(module, name)
                if (
                    isinstance(obj, type)
                    and hasattr(obj, "name")
                    and hasattr(obj, "execute")
                    and obj.__name__ != "BaseTool"
                ):
                    tool_instance = obj()
                    agent.register_tool(tool_instance)
                    print(f"[plugin] {py_file.name} → {tool_instance.name} yükləndi")
        except Exception as exc:
            print(f"[plugin] {py_file.name} yüklənmədi: {exc}")
```

**Plugin yazma nümunəsi:**
```python
# plugins/weather_tool.py — istifadəçi özü yazır
from agent.tools.base import BaseTool

class WeatherTool(BaseTool):
    name = "get_weather"
    description = "Şəhər üçün cari hava məlumatı al"

    def execute(self, city: str) -> str:
        # öz implementasiyan
        return f"{city}: 22°C, Günəşli"
```

---

## FAZA 7 — Desktop War Room Upgrade
**Həftə 7 | Prioritet: ORTA**

### 7.1 — Yeni UI Konsept

```
┌─────────────────── ApexForge Swarm War Room ─────────────────────┐
│  ┌──────────────────────────────────────────────────────┐  │
│  │              MISSION CONTROL                          │  │
│  │  Mission: Code Review                    [◼ STOP]    │  │
│  │  Status: ████████░░ 80%    Round: 2/3               │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐           │
│  │SUPERVISOR│────▶│ Worker 1 │     │ Worker 2 │           │
│  │          │     │ Security │     │ Architect│           │
│  │ Planning │◀────│ Analyst  │     │ Reviewer │           │
│  │ ████ 95% │     │ ████ 70% │     │ ███░ 60% │           │
│  └──────────┘     └──────────┘     └──────────┘           │
│                                                             │
│  ┌─────────────────┐  ┌────────────────────────────────┐  │
│  │  ASSIGNMENT FEED│  │  LIVE OUTPUT                   │  │
│  │                 │  │                                │  │
│  │ [W1] Sec check  │  │ Worker_1: Found SQL injection  │  │
│  │ [W2] Arch review│  │ in user_login() at line 42...  │  │
│  │ [SUP] Review    │  │                                │  │
│  └─────────────────┘  └────────────────────────────────┘  │
│                                                             │
│  Input: [________________________] [LAUNCH MISSION]        │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 — Yeni Frontend Xüsusiyyətləri

- **Mission Timeline** — hər round-un vizual göstəricisi
- **Worker Report Cards** — hər worker üçün ayrı panel
- **Tool Call Viz** — hansı tool çağırıldı, nə döndürdü
- **Mission Export** — PDF/Markdown formatında export
- **Mission Templates UI** — hazır şablonları seç
- **Real-time Progress Bar** — token/round əsasında

---

## FAZA 8 — Production Hazırlığı
**Həftə 8 | Prioritet: ORTA**

### 8.1 — Docker Support

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV LLM_PROVIDER=ollama
ENV OLLAMA_HOST=http://ollama:11434
ENV WEB_HOST=0.0.0.0
ENV WEB_PORT=8080

EXPOSE 8080

CMD ["python", "main.py", "--web"]
```

```yaml
# docker-compose.yml
services:
  apexforge:
    build: .
    ports:
      - "8080:8080"
    environment:
      - LLM_PROVIDER=ollama
      - OLLAMA_HOST=http://ollama:11434
    volumes:
      - ./memory:/app/memory
      - ./skills:/app/skills
      - ./sessions.db:/app/sessions.db
    depends_on:
      - ollama

  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama

volumes:
  ollama_data:
```

### 8.2 — Health Check Endpoint

```python
# agent/web/app.py
@app.get("/health")
async def health():
    models = []
    backend_ok = False
    try:
        models = _agent.available_models()
        backend_ok = True
    except Exception as e:
        pass
    
    return {
        "status": "ok" if backend_ok else "degraded",
        "backend": _config.agent.provider,
        "model": _config.ollama.model,
        "models_available": len(models),
        "session_count": len(_session_agents),
        "version": "2.0.0",
    }
```

### 8.3 — Rate Limiting

```python
# agent/web/app.py
from collections import defaultdict
import time

_request_counts: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 60  # dəqiqədə 60 sorğu

def check_rate_limit(client_ip: str):
    now = time.time()
    window = [t for t in _request_counts[client_ip] if now - t < 60]
    _request_counts[client_ip] = window
    if len(window) >= _RATE_LIMIT:
        raise HTTPException(429, "Rate limit exceeded. Try again in a minute.")
    _request_counts[client_ip].append(now)
```

---

## Tam İmplementasiya Yol Xəritəsi

```
HƏFTƏ 1          HƏFTƏ 2          HƏFTƏ 3          HƏFTƏ 4
─────────────    ─────────────    ─────────────    ─────────────
[x] max_tokens   [x] OpenAI       [x] Auth         [x] RAG ingest
[x] Streaming    [x] compat       [x] Sessions     [x] RAG search
[x] Token count  [x] backend      [x] SQLite       [x] RAG tool
[x] Error types  [x] auto-detect  [x] Rate limit   [x] Embed model

HƏFTƏ 5          HƏFTƏ 6          HƏFTƏ 7          HƏFTƏ 8
─────────────    ─────────────    ─────────────    ─────────────
[x] Mission      [x] Plugin       [x] War Room     [x] Docker
[x] templates    [x] loader       [x] UI v2        [x] Health check
[x] Agent msg    [x] Plugin API   [x] Timeline     [x] Rate limit
[x] Enhanced     [x] Examples     [x] Report cards [x] Docs
    reports
```

---

## Gözlənilən Nəticə

```
ƏVVƏL (indiki vəziyyət)          SONRA (8 həftə sonra)
────────────────────────         ──────────────────────
Ollama / llama.cpp only          + OpenAI / Groq / Mistral / LM Studio
max_tokens: 384                  max_tokens: 2048+ (konfiqurasiya edilə bilər)
No streaming (llama.cpp)         Real SSE streaming
No auth                          API key auth
In-memory sessions               SQLite persistent sessions
No RAG                           ChromaDB RAG + semantic search
Basic multi-agent                Mission templates + enhanced reports
No plugins                       Dynamic plugin system
Comic UI (basic)                 War Room v2 (mission timeline, report cards)
No Docker                        Docker + docker-compose
```

---

## Dependency Əlavələri

```txt
# requirements.txt-ə əlavə ediləcəklər
openai>=1.0.0          # OpenAI compat backend
chromadb>=0.5.0        # RAG vector store
pypdf>=4.0.0           # PDF ingestion
python-jose>=3.3.0     # JWT (optional, gələcək)
slowapi>=0.1.9         # Rate limiting (optional)
```

---

## Qeydlər

1. **Ardıcıllıq vacibdir** — Faza 1 bitməmiş Faza 2-yə keçmə. Streaming düzəlişi olmadan RAG test etmək çətin olur.
2. **Test yaz** — Hər yeni backend üçün minimal test əlavə et (`tests/test_openai_compat.py` etc.)
3. **Geriyə uyğunluq** — Mövcud `.env` faylları işləməlidir. Yeni env dəyişənləri optional olsun.
4. **Lokal-first prinsipi** — OpenAI compat əlavə edilsə də, sistem yenə Ollama/llama.cpp olmadan da işləməlidir.

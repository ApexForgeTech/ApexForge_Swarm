<div align="center">

<img src="assets/branding/main_logo.png" alt="ApexForge Swarm" width="360"/>

```
 █████╗ ██████╗ ███████╗██╗  ██╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗
██╔══██╗██╔══██╗██╔════╝╚██╗██╔╝██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
███████║██████╔╝█████╗   ╚███╔╝ █████╗  ██║   ██║██████╔╝██║  ███╗█████╗
██╔══██║██╔═══╝ ██╔══╝   ██╔██╗ ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝
██║  ██║██║     ███████╗██╔╝ ██╗██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝

███████╗██╗    ██╗ █████╗ ██████╗ ███╗   ███╗
██╔════╝██║    ██║██╔══██╗██╔══██╗████╗ ████║
███████╗██║ █╗ ██║███████║██████╔╝██╔████╔██║
╚════██║██║███╗██║██╔══██║██╔══██╗██║╚██╔╝██║
███████║╚███╔███╔╝██║  ██║██║  ██║██║ ╚═╝ ██║
╚══════╝ ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝
```

### Local-first · Tool-first · Multi-Agent · No Cloud Required

<p>
  <img src="https://img.shields.io/badge/Python-3.10%2B-1f6feb?style=for-the-badge&logo=python&logoColor=white">
  <img src="https://img.shields.io/badge/Runtime-Local--First-0f766e?style=for-the-badge">
  <img src="https://img.shields.io/badge/Backends-Ollama%20%7C%20llama.cpp%20%7C%20OpenAI-7c3aed?style=for-the-badge">
  <img src="https://img.shields.io/badge/Interfaces-CLI%20%7C%20Web%20%7C%20Desktop-b45309?style=for-the-badge">
  <img src="https://img.shields.io/badge/Multi--Agent-Supervisor%20%2B%20Workers-dc2626?style=for-the-badge">
</p>

**ApexForge Swarm** turns a local model into a system that can inspect, execute, plan, coordinate, and deliver real work — without sending your data anywhere.

[Quick Start](#quick-start) · [Architecture](#architecture) · [Backends](#backends) · [Multi-Agent](#multi-agent-system) · [RAG](#rag--knowledge-base) · [Desktop War Room](#desktop-war-room) · [Configuration](#configuration-guide) · [Roadmap](#roadmap)

</div>

---

## What Makes This Different From Ollama

```
Ollama                           ApexForge Swarm
──────                           ─────────
Chat completions API    vs.      Full agentic execution loop
Pull & run models       vs.      Tool-first task execution
Single model serving    vs.      Multi-backend (Ollama + llama.cpp + OpenAI compat)
No memory/context       vs.      Persistent memory + skills system
No multi-agent          vs.      Supervisor + parallel workers
API only                vs.      CLI + Web UI + Desktop War Room
No RAG                  vs.      ChromaDB vector search (local)
```

ApexForge Swarm is not a model server. It is a local AI agent platform built on top of model servers.

---

## Architecture

```
╔══════════════════════════════════════════════════════════════════════════╗
║                         USER INTERFACES                                  ║
║  ┌─────────────┐   ┌──────────────────┐   ┌───────────────────────────┐ ║
║  │   CLI       │   │   Web UI         │   │   Desktop War Room        │ ║
║  │  cli.py     │   │  FastAPI+WebSocket│   │  pywebview + comic_ui     │ ║
║  │             │   │  /ws streaming   │   │  Mission board            │ ║
║  └──────┬──────┘   └────────┬─────────┘   └─────────────┬─────────────┘ ║
╚═════════╪══════════════════╪═════════════════════════════╪═══════════════╝
          │                  │                             │
          └──────────────────┼─────────────────────────────┘
                             │
╔════════════════════════════╪═════════════════════════════════════════════╗
║                     CORE ENGINE                                          ║
║           ┌─────────────────────────────────┐                           ║
║           │         agent/core.py           │                           ║
║           │  ┌─────────────────────────┐    │                           ║
║           │  │  Chat Loop              │    │                           ║
║           │  │  • tool calling         │    │                           ║
║           │  │  • streaming            │    │                           ║
║           │  │  • context compression  │    │                           ║
║           │  │  • thought tag parsing  │    │                           ║
║           │  │  • interrupt/cancel     │    │                           ║
║           │  └─────────────────────────┘    │                           ║
║           └─────────────────────────────────┘                           ║
║                             │                                            ║
║        ┌────────────────────┼────────────────────┐                      ║
║        │                   │                    │                       ║
║ ┌──────▼──────┐   ┌────────▼────────┐   ┌──────▼──────┐               ║
║ │ LLM Backend │   │  Tool Executor  │   │   Memory    │               ║
║ │             │   │  + Fallbacks    │   │  + Skills   │               ║
║ │ Ollama      │   │                 │   │             │               ║
║ │ llama.cpp   │   │ shell→py→js     │   │ 2-layer     │               ║
║ │ OpenAI compat│  │ auto-fallback   │   │ global+prof │               ║
║ └─────────────┘   └─────────────────┘   └─────────────┘               ║
╚══════════════════════════════════════════════════════════════════════════╝
                             │
╔════════════════════════════╪═════════════════════════════════════════════╗
║                  MULTI-AGENT LAYER                                       ║
║           ┌─────────────────────────────────┐                           ║
║           │    MultiAgentSystem             │                           ║
║           │                                 │                           ║
║           │  ┌──────────┐  ┌─────────────┐ │                           ║
║           │  │Supervisor│  │  Workers    │ │                           ║
║           │  │          │  │ (parallel)  │ │                           ║
║           │  │ Plan     │  │ Worker_1    │ │                           ║
║           │  │ Review   │  │ Worker_2    │ │                           ║
║           │  │ Finalize │  │ Worker_N    │ │                           ║
║           │  └──────────┘  └─────────────┘ │                           ║
║           └─────────────────────────────────┘                           ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Quick Start

### 60-Second Setup

```bash
git clone https://github.com/ApexForgeTech/ApexForge_Swarm.git
cd ApexForge_Swarm
chmod +x setup.sh && ./setup.sh
source .venv/bin/activate
cp .env.example .env
# .env-ni redaktə et (backend seç)
python main.py
```

### Backend Seçimi

**Ollama (Ən Asan):**
```bash
ollama pull qwen2.5:7b
```
```env
LLM_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_NUM_CTX=16384
```

**llama.cpp (Ən Güclü — Local GGUF):**
```env
LLM_PROVIDER=llama_cpp
LLAMA_CPP_HOST=http://127.0.0.1:8081
LLAMA_CPP_MODEL_PATH=/path/to/model.gguf
LLAMA_CPP_AUTO_START=true
LLAMA_CPP_MAX_TOKENS=2048
LLAMA_CPP_REQUEST_TIMEOUT=600
```

**OpenAI / Groq / Mistral / LM Studio:**
```env
LLM_PROVIDER=openai_compat
OPENAI_COMPAT_API_KEY=sk-your-key-here
OPENAI_COMPAT_MODEL=gpt-4o-mini

# Groq (ultra-fast inference):
# OPENAI_COMPAT_BASE_URL=https://api.groq.com/openai/v1
# OPENAI_COMPAT_API_KEY=gsk_...
# OPENAI_COMPAT_MODEL=llama-3.3-70b-versatile

# LM Studio (fully local + OpenAI API):
# OPENAI_COMPAT_BASE_URL=http://localhost:1234/v1
# OPENAI_COMPAT_API_KEY=lm-studio
```

---

## Backends

```
┌───────────────────────────────────────────────────────────────┐
│                      BACKEND COMPARISON                        │
├────────────────┬─────────┬─────────────┬──────────────────────┤
│ Feature        │ Ollama  │ llama.cpp   │ OpenAI Compat        │
├────────────────┼─────────┼─────────────┼──────────────────────┤
│ Setup          │ Easy    │ Medium      │ Easy (API key)       │
│ Privacy        │ Local   │ Local       │ Cloud (optional)     │
│ Speed          │ Good    │ Fastest     │ Very Fast (Groq)     │
│ Streaming      │ Yes     │ Yes         │ Yes                  │
│ Tool calling   │ Yes     │ Yes         │ Yes                  │
│ Model choice   │ Many    │ Any GGUF    │ GPT-4o, Claude, etc. │
│ Auto-start     │ No      │ Yes         │ No                   │
│ Multi-agent    │ Parallel│ Serialized  │ Parallel             │
│ Local discovery│ Yes     │ Yes         │ No                   │
└────────────────┴─────────┴─────────────┴──────────────────────┘
```

### Backend Auto-Detection

ApexForge Swarm yüklənəndə mövcud backendləri yoxlayır:

```
[startup] Checking backends...
  ✓ ollama     — http://localhost:11434 (3 models)
  ✓ llama_cpp  — http://127.0.0.1:8081 (ready)
  ✗ openai     — no API key configured
[startup] Active: llama_cpp
```

---

## Run Modes

### Interactive CLI
```bash
python main.py
python main.py --profile work          # named profile
python main.py --resume                # resume last session
python main.py --session 20260506_142015
```

### One-Shot Prompt
```bash
python main.py -p "list current files"
python main.py -p "analyze this repository" --plain
```

### Parallel Prompts
```bash
python main.py \
  --parallel-prompt "summarize this project" \
  --parallel-prompt "list the main modules" \
  --plain
```

### Multi-Agent Mission
```bash
python main.py --multi-agent -p "review this codebase and suggest improvements"

# Mission template ilə:
python main.py --multi-agent --template code_review -p "review agent/core.py"
```

### Web UI
```bash
python main.py --web
# → http://127.0.0.1:8080
```

### Desktop War Room
```bash
python main.py --desktop
# Fallback (pywebview yoxdursa):
APEXFORGE_ALLOW_DESKTOP_WEB_FALLBACK=true python main.py --desktop
```

---

## Multi-Agent System

### Necə İşləyir

```
User Request
     │
     ▼
┌────────────────────────────────────────────────────────────┐
│                    ROUND 1                                  │
│                                                            │
│  Supervisor                                                │
│  ├─ Plans mission                                          │
│  ├─ Assigns tasks to workers                               │
│  └─ Defines success criteria                               │
│                         │                                  │
│         ┌───────────────┼───────────────┐                  │
│         ▼               ▼               ▼                  │
│    Worker_1        Worker_2        Worker_3                │
│    (parallel)      (parallel)      (parallel)              │
│    executes        executes        executes                │
│    tools           tools           tools                   │
│         │               │               │                  │
│         └───────────────┼───────────────┘                  │
│                         ▼                                  │
│  Supervisor reviews worker reports                         │
│  ├─ "complete" → Final answer → Done                       │
│  └─ "revise"  → Round 2 with targeted feedback             │
└────────────────────────────────────────────────────────────┘
     │
     ▼
Final Answer (max 3 rounds)
```

### Mission Templates

```bash
# Kod Review
python main.py --multi-agent --template code_review \
  -p "review the authentication module"

# Research
python main.py --multi-agent --template research \
  -p "research the best local embedding models for RAG"

# Repo Audit
python main.py --multi-agent --template repo_audit \
  -p "audit this entire repository"

# Document Processing
python main.py --multi-agent --template document_processing \
  -p "process and summarize the attached report"
```

**Available templates:**

```
code_review        — Security + Architecture + Test Coverage analysts
research           — Web Researcher + Analyst + Fact Checker
repo_audit         — Codebase Explorer + Risk Analyst + Planner
document_processing— Content Extractor + Summarizer + Action Items
```

### Custom Team

```bash
python main.py --multi-agent \
  --supervisor "Project Lead" \
  --worker "Backend Developer" \
  --worker "Frontend Developer" \
  --worker "DevOps Engineer" \
  -p "plan the deployment of this application"
```

---

## Tool System

### Built-in Tools

```
┌─────────────────────────────────────────────────────────────┐
│                        TOOL MAP                              │
├───────────────────┬────────────────────────────────────────-┤
│ Category          │ Tools                                    │
├───────────────────┼──────────────────────────────────────────┤
│ Files             │ read_file, write_file, edit_file,        │
│                   │ list_directory, search_files             │
├───────────────────┼──────────────────────────────────────────┤
│ Shell             │ run_shell (bash commands)                │
├───────────────────┼──────────────────────────────────────────┤
│ Code Execution    │ run_python, run_javascript               │
├───────────────────┼──────────────────────────────────────────┤
│ Documents         │ read_document (pdf, docx, xlsx, csv)     │
├───────────────────┼──────────────────────────────────────────┤
│ Web               │ fetch_url, web_search                    │
├───────────────────┼──────────────────────────────────────────┤
│ Memory            │ remember, recall                         │
├───────────────────┼──────────────────────────────────────────┤
│ RAG               │ rag_ingest, rag_search                   │
└───────────────────┴──────────────────────────────────────────┘
```

### Tool Fallback System

When a tool fails, ApexForge Swarm automatically tries alternatives:

```
search_files fails
       │
       ├─▶ run_shell (rg / grep)
       │          │
       │          ├─▶ Succeeds → Return result
       │          └─▶ Fails
       │                  │
       ├─▶ run_python (pathlib + regex)
       │          │
       │          ├─▶ Succeeds → Return result
       │          └─▶ Fails
       │
       └─▶ run_javascript (fs.readFileSync)
```

Same fallback chain exists for: `list_directory`, `read_file`, `fetch_url`, `web_search`, `edit_file`, `read_document`.

---

## RAG — Knowledge Base

ApexForge Swarm includes a local vector search system for working with large document collections that don't fit in the model's context window.

### Setup

```bash
pip install chromadb pypdf
ollama pull nomic-embed-text   # local embedding model
```

### Usage

```bash
# Sənəd əlavə et
python main.py -p "ingest /path/to/report.pdf into the knowledge base"

# Sorğu ver
python main.py -p "search the knowledge base for authentication best practices"

# Böyük codebase analizi
python main.py -p "ingest the entire src/ directory, then find all database queries"
```

### How It Works

```
Document
   │
   ▼ chunk (500 words, 50 overlap)
Chunks
   │
   ▼ nomic-embed-text (local, via Ollama)
Vectors
   │
   ▼ ChromaDB (persistent, local)
Vector Store
   │
   ▼ semantic search at query time
Top-K Relevant Chunks
   │
   ▼ injected into agent context
Answer
```

---

## Memory & Skills

### Memory System (2-Layer)

```
┌─────────────────────────────────────┐
│           Profile Layer             │  ← profiles/NAME/memory/
│  (overrides global for this user)   │
├─────────────────────────────────────┤
│           Global Layer              │  ← memory/
│  (shared across all profiles)       │
└─────────────────────────────────────┘
```

```bash
# Agent bu session-u xatırlayacaq
> remember that the database host is db.internal:5432

# Sonrakı sessiyalarda da işləyir
> what's the database host?
→ db.internal:5432
```

### Skills System

Skills are persistent behavioral rules injected into every prompt:

```
skills/
├── coding.md          # kodu necə yaz
├── git_workflow.md    # git qaydaları
├── file_editing.md    # fayl redaktə prinsipləri
└── model_selection.md # hansı model nə vaxt
```

```yaml
# skills/coding.md frontmatter
---
title: Coding Standards
priority: high        # critical | high | normal | low
summary: Follow these rules when writing or editing code
triggers:
  - user asks to write code
  - user asks to edit a file
mandatory:
  - Write no unnecessary comments
  - Prefer editing existing files over creating new ones
---
```

---

## Desktop War Room

The visual command center for multi-agent missions.

```
╔═══════════════════════════════════════════════════════════════╗
║              ◈  APEXFORGE WAR ROOM  ◈                        ║
║═══════════════════════════════════════════════════════════════║
║  Mission: "Review authentication module"  [Round 2/3]  ◼STOP ║
║  Progress: ████████████░░░░░░ 65%                             ║
╠═══════════════════════════════════════════════════════════════║
║                                                               ║
║       ┌──────────────┐                                        ║
║       │  SUPERVISOR  │  Planning → Assigning → Reviewing      ║
║       │  Sr. Reviewer│                                        ║
║       └──────┬───────┘                                        ║
║              │ assigns                                         ║
║    ┌─────────┼─────────┐                                      ║
║    ▼         ▼         ▼                                       ║
║ ┌───────┐ ┌───────┐ ┌───────┐                                 ║
║ │Worker1│ │Worker2│ │Worker3│                                 ║
║ │Sec.   │ │Arch.  │ │Test   │                                 ║
║ │Analyst│ │Review │ │Analyst│                                 ║
║ │████90%│ │███70% │ │██50% │                                  ║
║ └───────┘ └───────┘ └───────┘                                 ║
╠═══════════════════════════════════════════════════════════════║
║  FEED                    │  LIVE OUTPUT                        ║
║  [W1] SQL injection found │  Worker_1: Found vulnerability in  ║
║  [W2] No auth middleware  │  user_login() — unsanitized input  ║
║  [W3] 0% test coverage   │  at auth/login.py:42...            ║
╠═══════════════════════════════════════════════════════════════║
║  > [Enter mission or select template ▼]     [LAUNCH] [CLEAR]  ║
╚═══════════════════════════════════════════════════════════════╝
```

```bash
python main.py --desktop

# Native desktop (pywebview + PyQt6):
pip install pywebview PyQt6 PyQt6-WebEngine

# Browser fallback:
APEXFORGE_ALLOW_DESKTOP_WEB_FALLBACK=true python main.py --desktop
```

---

## Web API

The web server exposes a full REST API + WebSocket streaming.

### Endpoints

```
GET  /                    → Web UI (index.html)
GET  /api/models          → list available models
GET  /api/config          → current configuration
POST /api/config          → update configuration
POST /api/clear           → clear conversation
POST /api/reload          → reload memory/skills
GET  /api/export          → export conversation (Markdown)
POST /api/batch           → batch prompts (parallel)

GET  /api/skills          → list all skills
GET  /api/skills/{name}   → get skill content
POST /api/skills/{name}   → save skill
DEL  /api/skills/{name}   → delete skill

GET  /api/memory          → list memory entries
GET  /api/memory/{name}   → get memory entry
POST /api/memory/{name}   → save memory
DEL  /api/memory/{name}   → delete memory

GET  /api/missions        → mission history
GET  /api/missions/{id}   → get specific mission

GET  /health              → system health check

WS   /ws                  → WebSocket streaming
```

### WebSocket Protocol

```javascript
// Connect
const ws = new WebSocket("ws://localhost:8080/ws");

// Send message
ws.send(JSON.stringify({
  message: "analyze this codebase",
  session_id: "my-session",   // optional
  images: [],                  // optional base64 images
}));

// Receive events
ws.onmessage = (e) => {
  const event = JSON.parse(e.data);
  // event.type: "session" | "text" | "thought" | "tool_call" |
  //             "tool_result" | "error" | "done"
};
```

### Batch API

```bash
curl -X POST http://localhost:8080/api/batch \
  -H "Content-Type: application/json" \
  -d '{
    "prompts": [
      "summarize the main module",
      "list all Python files",
      "count lines of code"
    ],
    "max_workers": 3,
    "multi_agent": false
  }'
```

---

## Configuration Guide

### Environment Variables

```
┌─────────────────────────────────────────────────────────────┐
│                  CORE CONFIGURATION                          │
├──────────────────────────────┬──────────────────────────────┤
│ Variable                     │ Purpose                      │
├──────────────────────────────┼──────────────────────────────┤
│ LLM_PROVIDER                 │ ollama / llama_cpp /         │
│                              │ openai_compat                │
│ OLLAMA_HOST                  │ Ollama server URL            │
│ OLLAMA_MODEL                 │ Model name                   │
│ OLLAMA_TEMPERATURE           │ Sampling (default: 0.2)      │
│ OLLAMA_NUM_CTX               │ Context window (default:     │
│                              │ 16384)                       │
├──────────────────────────────┼──────────────────────────────┤
│ LLAMA_CPP_HOST               │ llama.cpp server URL         │
│ LLAMA_CPP_MODEL_PATH         │ Absolute GGUF path           │
│ LLAMA_CPP_HF_MODEL           │ HuggingFace model ID         │
│ LLAMA_CPP_AUTO_START         │ true/false                   │
│ LLAMA_CPP_MAX_TOKENS         │ Max output tokens (def: 2048)│
│ LLAMA_CPP_REQUEST_TIMEOUT    │ Seconds (default: 600)       │
├──────────────────────────────┼──────────────────────────────┤
│ OPENAI_COMPAT_API_KEY        │ API key                      │
│ OPENAI_COMPAT_BASE_URL       │ Base URL (empty = OpenAI)    │
│ OPENAI_COMPAT_MODEL          │ Model ID                     │
│ OPENAI_COMPAT_MAX_TOKENS     │ Max tokens (default: 4096)   │
├──────────────────────────────┼──────────────────────────────┤
│ WEB_HOST                     │ Bind host (default: 0.0.0.0) │
│ WEB_PORT                     │ Port (default: 8080)         │
│ APEXFORGE_API_KEY            │ Web API auth key (optional)  │
├──────────────────────────────┼──────────────────────────────┤
│ APEXFORGE_SERIALIZE_LLM_     │ Force request serialization  │
│ REQUESTS                     │ (safer for fragile backends) │
│ APEXFORGE_ALLOW_DESKTOP_     │ Browser fallback for desktop │
│ WEB_FALLBACK                 │ mode                         │
│ AUX_AUTONOMY_ENABLED         │ Enable ! shell prefix        │
└──────────────────────────────┴──────────────────────────────┘
```

### config.yaml

```yaml
agent:
  provider: llama_cpp          # ollama | llama_cpp | openai_compat
  max_iterations: 12
  system_prompt: "You are ApexForge Swarm..."

ollama:
  host: http://localhost:11434
  model: qwen2.5:7b
  num_ctx: 16384
  temperature: 0.2

llama_cpp:
  host: http://127.0.0.1:8081
  model_path: ""
  auto_start: false
  max_tokens: 2048             # was 384 — now sensible default
  request_timeout: 600
  jinja: true

web:
  host: 0.0.0.0
  port: 8080
```

---

## Plugin System

Add custom tools without modifying core code:

```
plugins/
├── weather_tool.py
├── slack_notifier.py
└── github_tool.py
```

```python
# plugins/my_tool.py
from agent.tools.base import BaseTool

class MyCustomTool(BaseTool):
    name = "my_tool"
    description = "What this tool does"

    def execute(self, param1: str, param2: int = 10) -> str:
        # your implementation
        return f"Result: {param1} × {param2}"
```

Tools in `plugins/` are automatically discovered and registered at startup.

---

## Repository Map

```
ApexForge_Swarm/
│
├── main.py                    ← Entry point (CLI / Web / Desktop)
├── cli.py                     ← Terminal UX, session management
├── config.yaml                ← Default configuration
├── .env.example               ← Environment variables template
├── requirements.txt           ← Python dependencies
├── setup.sh                   ← One-command setup
│
├── agent/
│   ├── core.py                ← Main execution loop
│   ├── llm_backend.py         ← Ollama / llama.cpp / OpenAI compat
│   ├── multi_agent.py         ← Supervisor + worker orchestration
│   ├── tool_executor.py       ← Tool dispatch + fallback chains
│   ├── memory.py              ← Skills + memory 2-layer system
│   ├── rag.py                 ← Vector search (ChromaDB)
│   ├── config.py              ← Configuration dataclasses
│   ├── runtime.py             ← Tool registration
│   ├── session.py             ← Session persistence
│   ├── session_store.py       ← SQLite mission/session storage
│   ├── events.py              ← Event type definitions
│   ├── reporting.py           ← Worker report normalization
│   ├── request_router.py      ← Direct tool routing
│   ├── system_prompt.py       ← Prompt construction
│   ├── mission_templates.py   ← Predefined team configurations
│   ├── errors.py              ← Structured error types
│   ├── plugin_loader.py       ← Dynamic tool loading
│   │
│   ├── tools/                 ← Built-in tool implementations
│   │   ├── base.py
│   │   ├── file_tools.py
│   │   ├── shell_tools.py
│   │   ├── code_tools.py
│   │   ├── web_tools.py
│   │   ├── doc_tools.py
│   │   └── memory_tools.py
│   │
│   └── web/
│       ├── app.py             ← FastAPI server
│       ├── desktop.py         ← pywebview bridge
│       ├── auth.py            ← API key authentication
│       └── static/
│           ├── index.html     ← Web UI
│           └── comic_ui.html  ← Desktop War Room
│
├── plugins/                   ← Custom tools (auto-loaded)
├── skills/                    ← Agent behavioral rules
├── memory/                    ← Persistent memory
├── profiles/                  ← Per-user profiles
├── tests/                     ← Test suite
└── docs/
    ├── IMPLEMENTATION_PLAN.md ← Full development roadmap
    ├── ROADMAP.md             ← Phase overview
    ├── PROJECT_AUDIT.md       ← Technical assessment
    └── TROUBLESHOOTING.md     ← Common problems & fixes
```

---

## Feature Matrix

```
┌─────────────────────────────────────────────────────────────┐
│                     CAPABILITY MATRIX                        │
├──────────────────────────────────────┬──────────┬───────────┤
│ Capability                           │ Status   │ Notes     │
├──────────────────────────────────────┼──────────┼───────────┤
│ File read/write/edit                 │ ✓        │           │
│ Directory listing                    │ ✓        │           │
│ File search (grep/rg)                │ ✓        │ +fallback │
│ Shell command execution              │ ✓        │           │
│ Python code execution                │ ✓        │           │
│ JavaScript code execution            │ ✓        │           │
│ PDF / DOCX / XLSX / CSV reading      │ ✓        │           │
│ Web fetch / search                   │ ✓        │ +fallback │
│ Persistent memory                    │ ✓        │           │
│ Skill rules                          │ ✓        │           │
│ RAG / vector search                  │ ✓        │ ChromaDB  │
│ Tool fallback chains                 │ ✓        │           │
│ Streaming responses                  │ ✓        │           │
│ Interrupt / cancel                   │ ✓        │           │
│ Context auto-compression             │ ✓        │           │
│ Thinking tag support                 │ ✓        │ <thought> │
│ Image input                          │ ✓        │ base64    │
│ CLI interactive mode                 │ ✓        │           │
│ CLI one-shot / parallel prompts      │ ✓        │           │
│ Web UI (FastAPI + WebSocket)         │ ✓        │           │
│ Desktop War Room                     │ ✓        │ pywebview │
│ Multi-agent orchestration            │ ✓        │           │
│ Mission templates                    │ ✓        │           │
│ Session persistence (SQLite)         │ ✓        │           │
│ Mission history                      │ ✓        │           │
│ Plugin / custom tools                │ ✓        │           │
│ API authentication                   │ ✓        │ API key   │
│ Batch API                            │ ✓        │           │
│ Docker support                       │ ✓        │           │
│ Multi-profile support                │ ✓        │           │
│ Ollama backend                       │ ✓        │           │
│ llama.cpp backend (auto-start)       │ ✓        │           │
│ OpenAI / Groq / Mistral backend      │ ✓        │           │
└──────────────────────────────────────┴──────────┴───────────┘
```

---

## Example Missions

### Repository Analysis

```bash
python main.py -p "inspect this repository and identify the highest-risk problems"
```

### Code Review (Multi-Agent)

```bash
python main.py --multi-agent --template code_review \
  -p "do a full security and architecture review of the agent/ directory"
```

### Document Processing

```bash
python main.py --multi-agent --template document_processing \
  -p "process docs/requirements.pdf and extract action items"
```

### Codebase RAG + Query

```bash
# Codebase-i bilgi bazasına əlavə et
python main.py -p "ingest all Python files in this project into the knowledge base"

# Böyük codebase üzərindən sorğu ver
python main.py -p "search the knowledge base: where is authentication handled?"
```

### Parallel Research

```bash
python main.py \
  --parallel-prompt "what is the best local embedding model for RAG?" \
  --parallel-prompt "compare ChromaDB vs FAISS for local use" \
  --parallel-prompt "how does nomic-embed-text compare to sentence-transformers?" \
  --plain
```

---

## Docker

```bash
# Build & run
docker-compose up -d

# Only ApexForge Swarm (external Ollama):
docker build -t apexforge .
docker run -p 8080:8080 \
  -e LLM_PROVIDER=ollama \
  -e OLLAMA_HOST=http://host.docker.internal:11434 \
  -v ./memory:/app/memory \
  -v ./skills:/app/skills \
  apexforge
```

---

## Roadmap

```
Phase 1 — Core Fixes          ████████████████████ Done
  max_tokens fix, streaming, error types, token count

Phase 2 — New Backends        ████████████████░░░░ In Progress
  OpenAI compat, auto-detection, backend registry

Phase 3 — Security + Storage  ████████░░░░░░░░░░░░ Planned
  API auth, SQLite sessions, mission history

Phase 4 — RAG System          ████████░░░░░░░░░░░░ Planned
  ChromaDB, embeddings, ingest pipeline, search tool

Phase 5 — Multi-Agent v2      ████░░░░░░░░░░░░░░░░ Planned
  Mission templates, enhanced reports, agent messaging

Phase 6 — Plugin System       ████░░░░░░░░░░░░░░░░ Planned
  Dynamic tool loading, plugin API, examples

Phase 7 — War Room v2         ██░░░░░░░░░░░░░░░░░░ Planned
  Mission timeline, report cards, progress bars

Phase 8 — Production          ██░░░░░░░░░░░░░░░░░░ Planned
  Docker, health check, rate limiting, full docs
```

Full plan: [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)

---

## Troubleshooting

### llama.cpp server unreachable

```bash
# Server-i əl ilə başlat
llama-server -m /path/to/model.gguf --host 127.0.0.1 --port 8081 -c 16384

# Və ya auto-start aktiv et:
LLAMA_CPP_AUTO_START=true python main.py
```

### Workers hit HTTP 500 (multi-agent)

Request serialization aktiv et:
```bash
APEXFORGE_SERIALIZE_LLM_REQUESTS=true python main.py --desktop
```

### Desktop opens browser instead of native window

```bash
# Dependencies yüklə:
pip install pywebview PyQt6 PyQt6-WebEngine

# Və ya browser fallback-i icazə ver:
APEXFORGE_ALLOW_DESKTOP_WEB_FALLBACK=true python main.py --desktop
```

### Responses cut off (llama.cpp)

`max_tokens` artır:
```env
LLAMA_CPP_MAX_TOKENS=2048
```

### Model loads slowly / timeout

```env
LLAMA_CPP_STARTUP_TIMEOUT=120
LLAMA_CPP_REQUEST_TIMEOUT=600
```

Daha çox: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

---

## CLI Reference

```bash
python main.py --help

Options:
  --profile NAME          Named profile
  --resume                Resume last session
  --session ID            Resume specific session
  -p, --prompt TEXT       One-shot prompt
  --plain                 Plain text output (no formatting)
  --parallel-prompt TEXT  Parallel prompt (repeatable)
  --multi-agent           Enable multi-agent mode
  --template NAME         Mission template
  --supervisor ROLE       Supervisor role description
  --worker ROLE           Worker role (repeatable)
  --web                   Launch web server
  --desktop               Launch desktop war room
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Follow the implementation plan in [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)
4. Add tests for new code
5. Submit a pull request

---

## License

No license file is currently included. Add one before public release.

---

<div align="center">

**ApexForge Swarm** — Built for real work, not just chat.

*Local models. Real tools. Actual execution.*

</div>

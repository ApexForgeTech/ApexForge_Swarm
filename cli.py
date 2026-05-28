"""
ApexForge Swarm — Terminal interface
Usage:
  python main.py                         # interactive, default profile
  python main.py --profile work          # named profile
  python main.py --resume                # resume last session
  python main.py -p "your question"      # direct prompt, no interactive mode
"""
import copy
import os
import sys
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text
from prompt_toolkit import PromptSession, prompt
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style

from agent.config import Config
from agent.core import Agent
from agent.memory import MemorySystem
from agent.multi_agent import MultiAgentSystem
from agent.profile import Profile
from agent.runtime import build_agent
from agent.session import Session
from agent import credentials

console = Console()
err_console = Console(stderr=True)

BANNER = r"""[bold cyan]
   ___                  ____
  / _ | ___  ___ __ __/ __/__  _______ ____ ___
 / __ |/ _ \/ -_) \ / _/ / _ \/ __/ _ `/ -_)_  /
/_/ |_/ .__/\__/_\_/_/ \___/_/  \_, /\__//__/
     /_/       [dim]ApexForge Swarm[/dim]      /___/
[/bold cyan]"""

TOOL_ICONS = {
    "run_shell": "⚡", "run_python": "🐍", "run_javascript": "🟨", "read_file": "📖",
    "write_file": "✏", "list_directory": "📂", "search_files": "🔍",
    "create_directory": "📁", "delete_path": "🗑", "move_path": "✂",
    "edit_file": "📝",
    "fetch_url": "🌐", "web_search": "🌐", "read_document": "📄",
    "remember": "💾", "recall": "🧠", "learn_skill": "📚",
}

SLASH_CMDS = [
    "/help", "/exit", "/quit", "/status", "/clear", "/new",
    "/model", "/models", "/pull", "/del", "/skills", "/memory", "/reload",
    "/sessions", "/resume", "/export", "/history", "/tokens",
    "/profile", "/profiles", "/whoami", "/compact",
]


# ── Credential onboarding ──────────────────────────────────────────────────

def ensure_credentials() -> dict:
    """Show first-run setup if no credentials exist. Returns credentials."""
    creds = credentials.load()
    if creds:
        return creds

    # First run!
    console.print(BANNER)
    console.print(Panel(
        "[bold]Welcome to ApexForge Swarm![/bold]\n\n"
        "This is your first run. Let's set up your local credentials.\n"
        "Your key is generated from your machine and stored locally — "
        "[dim]never sent anywhere.[/dim]",
        border_style="cyan",
        title="[bold cyan]First Run Setup[/bold cyan]",
    ))
    console.print()

    try:
        username = prompt(
            "Enter your name (or press Enter to use system username): ",
            style=Style.from_dict({"": "bold cyan"}),
        ).strip()
    except (KeyboardInterrupt, EOFError):
        import getpass
        username = ""

    if not username:
        import getpass
        username = getpass.getuser()

    creds = credentials.create(username)

    console.print()
    console.print(Panel(
        f"[green]✓ Credentials created![/green]\n\n"
        f"  User:    [bold]{creds['username']}[/bold]\n"
        f"  Key:     [dim]{credentials.key_short(creds)}[/dim]\n"
        f"  Machine: {creds['machine']}\n"
        f"  Plan:    [cyan]{creds['plan']}[/cyan]\n"
        f"  Stored:  [dim]{credentials.CREDS_FILE}[/dim]",
        border_style="green",
        title="[bold green]Setup Complete[/bold green]",
    ))
    console.print()
    return creds


# ── Agent factory ──────────────────────────────────────────────────────────

def make_agent(config: Config, profile: Profile) -> Agent:
    memory = MemorySystem(
        global_skills_dir=config.skills_path,
        global_memory_dir=config.memory_path,
        profile_skills_dir=profile.skills_dir,
        profile_memory_dir=profile.memory_dir,
    )
    return build_agent(config, memory=memory)


# ── Auto memory extraction ─────────────────────────────────────────────────

def _auto_extract_memory(agent: Agent, session: Session, config: Config, silent: bool = True):
    """At session end, ask agent to save any important info to memory."""
    if session.turn_count < 2:
        return

    extract_prompt = (
        "Before we end this session, review our conversation. "
        "Use the `remember` tool to save any important information you learned "
        "(user preferences, project facts, key decisions, useful context). "
        "If nothing new was learned, just say 'Nothing new to save.' "
        "Be brief — only save genuinely useful facts for future sessions."
    )

    if not silent:
        console.print("[dim]  Extracting memories from session…[/dim]")

    for ev in agent.chat(extract_prompt):
        if ev["type"] == "tool_result" and not silent:
            d = ev["data"]
            if d["name"] == "remember":
                console.print(f"  [dim]💾 {d['result']}[/dim]")
        elif ev["type"] == "done":
            break
        elif ev["type"] == "error":
            break


# ── Direct prompt mode (-p) ────────────────────────────────────────────────

def run_direct_prompt(
    config: Config,
    prompt_text: str,
    profile_name: str = "default",
    plain: bool = False,
):
    """Run a single prompt and print the result. No interactive session."""
    profile = Profile.get_or_create(profile_name)
    profile.ensure_dirs()
    if profile.model and not getattr(config, "_explicit_model_override", False):
        config.ollama.model = profile.model

    agent = make_agent(config, profile)

    full_response = ""
    tool_outputs = []

    for ev in agent.chat(prompt_text):
        t = ev["type"]
        if t == "text":
            full_response += ev["data"]
        elif t == "tool_call":
            d = ev["data"]
            icon = TOOL_ICONS.get(d["name"], "⚙")
            if not plain:
                err_console.print(f"[dim]{icon} {d['name']}…[/dim]")
        elif t == "tool_result":
            d = ev["data"]
            tool_outputs.append(f"[{d['name']}]: {d['result'][:200]}")
        elif t == "error":
            err_console.print(f"[red]Error:[/red] {ev['data']}")
            sys.exit(1)
        elif t == "done":
            break

    if plain:
        # Strip markdown for piping
        import re
        clean = re.sub(r"[*`#>]", "", full_response).strip()
        print(clean)
    else:
        console.print(Markdown(full_response))

    credentials.increment(sessions=1, messages=1)


def run_parallel_prompts(
    config: Config,
    prompts: list[str],
    profile_name: str = "default",
    plain: bool = False,
    multi_agent: bool = False,
    template: str = "",
    supervisor_role: str = "",
    worker_roles: list[str] | None = None,
):
    profile = Profile.get_or_create(profile_name)
    profile.ensure_dirs()

    def run_one(index: int, prompt_text: str):
        cfg = copy.deepcopy(config)
        if profile.model and not getattr(cfg, "_explicit_model_override", False):
            cfg.ollama.model = profile.model

        if multi_agent:
            if template:
                sup_override = {"role": supervisor_role} if supervisor_role else None
                wkr_override = [{"role": r} for r in worker_roles] if worker_roles else None
                mas = MultiAgentSystem.from_template(cfg, template, supervisor_override=sup_override, workers_override=wkr_override)
            else:
                supervisor_data = {"role": supervisor_role or "Supervisor"}
                workers_data = (
                    [{"role": r} for r in worker_roles]
                    if worker_roles
                    else [{"role": "Developer"}, {"role": "Researcher"}, {"role": "Verifier"}]
                )
                mas = MultiAgentSystem(cfg, supervisor_data, workers_data)
            final_answer = ""
            fallback_parts = []
            for ev in mas.chat(prompt_text):
                if ev["type"] == "agent_chat" and ev.get("data"):
                    fallback_parts.append(ev["data"])
                if ev["type"] == "final":
                    final_answer = ev["data"]
            if not final_answer:
                final_answer = "".join(fallback_parts)
            return index, prompt_text, final_answer.strip()

        agent = make_agent(cfg, profile)
        parts = []
        for ev in agent.chat(prompt_text):
            if ev["type"] == "text":
                parts.append(ev["data"])
            elif ev["type"] == "error":
                return index, prompt_text, f"Error: {ev['data']}"
            elif ev["type"] == "done":
                break
        return index, prompt_text, "".join(parts).strip()

    results = []
    with ThreadPoolExecutor(max_workers=max(1, len(prompts))) as executor:
        future_map = {
            executor.submit(run_one, idx, prompt): idx
            for idx, prompt in enumerate(prompts)
        }
        for future in as_completed(future_map):
            results.append(future.result())

    for index, prompt_text, output in sorted(results, key=lambda item: item[0]):
        if plain:
            print(f"[{index + 1}] {prompt_text}")
            print(output)
            print()
        else:
            console.print(Panel(Markdown(output or "_No response_"), title=f"Prompt {index + 1}: {prompt_text}", border_style="cyan"))


# ── Interactive CLI ────────────────────────────────────────────────────────

def run_cli(
    config: Config,
    profile_name: str = "default",
    resume: bool = False,
    session_id: Optional[str] = None,
    creds: dict = None,
):
    profile = Profile.get_or_create(profile_name)
    profile.ensure_dirs()
    if profile.model and not getattr(config, "_explicit_model_override", False):
        config.ollama.model = profile.model
    if profile.temperature is not None:
        config.ollama.temperature = profile.temperature
    if profile.num_ctx is not None:
        config.ollama.num_ctx = profile.num_ctx

    agent = make_agent(config, profile)

    # Session
    if resume or session_id:
        sid = session_id or Session.latest_id(profile.sessions_dir)
        if sid:
            session = Session(profile.sessions_dir, session_id=sid, model=config.ollama.model)
            msgs = session.resumed_messages
            if msgs:
                agent.load_messages(msgs)
                console.print(
                    f"[dim]  Resumed session [cyan]{sid}[/cyan] "
                    f"({session.turn_count} turns, {session.created_display})[/dim]"
                )
            else:
                console.print("[yellow]  No resumable messages — starting fresh.[/yellow]")
                session = Session(profile.sessions_dir, model=config.ollama.model)
        else:
            console.print("[yellow]  No sessions found — starting fresh.[/yellow]")
            session = Session(profile.sessions_dir, model=config.ollama.model)
    else:
        session = Session(profile.sessions_dir, model=config.ollama.model)
    session.model = config.ollama.model

    # Interrupt
    interrupt_evt = threading.Event()
    original_sigint = signal.getsignal(signal.SIGINT)

    def sigint_stream(sig, frame):
        interrupt_evt.set()

    # Banner
    console.print(BANNER)
    user_display = f"[dim]{creds['username']}[/dim]  " if creds else ""
    console.print(
        f"  {user_display}"
        f"Profile: [bold magenta]{profile_name}[/bold magenta]  "
        f"Provider: [bold cyan]{config.agent.provider}[/bold cyan]  "
        f"Model: [bold green]{config.ollama.model}[/bold green]  "
        f"Session: [dim]{session.id}[/dim]\n"
        f"  Skills: [yellow]{len(agent.memory.list_skills())}[/yellow]  "
        f"Memories: [yellow]{len(agent.memory.list_memories())}[/yellow]\n"
    )
    console.print("[dim]  /help for commands · Ctrl+C = interrupt generation · /exit to quit[/dim]\n")

    # Prompt session
    completer = WordCompleter(SLASH_CMDS, sentence=True)
    prompt_session = PromptSession(
        history=FileHistory(str(Path.home() / f".apexforge_{profile_name}_history")),
        completer=completer,
        style=Style.from_dict({"prompt": "bold cyan"}),
        complete_while_typing=False,
    )

    msg_count = 0

    while True:
        signal.signal(signal.SIGINT, original_sigint)
        model_short = config.ollama.model.split(":")[0]
        prompt_str = f"[{profile_name}@{model_short}] > "

        try:
            user_input = prompt_session.prompt(prompt_str).strip()
        except KeyboardInterrupt:
            console.print("\n[dim]  Ctrl+C — type [cyan]/exit[/cyan] to quit.[/dim]")
            continue
        except EOFError:
            _on_exit(agent, session, config, creds, msg_count)
            break

        if not user_input:
            continue

        user_input = _normalize_cli_command_input(user_input)

        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("/exit", "/quit"):
                _on_exit(agent, session, config, creds, msg_count)
                break

            if cmd == "/new":
                _auto_extract_memory(agent, session, config, silent=True)
                agent.clear()
                session = Session(profile.sessions_dir, model=config.ollama.model)
                console.print(f"[green]New session:[/green] [dim]{session.id}[/dim]")
                msg_count = 0
                continue

            _handle_slash(cmd, arg, agent, config, profile, session, profile_name, creds)
            continue

        # Agent chat
        signal.signal(signal.SIGINT, sigint_stream)
        interrupt_evt.clear()

        console.print()
        response_text = ""
        preflight_error = None

        with Live(
            Spinner("dots2", text=f"  [dim]{config.ollama.model}[/dim] thinking…"),
            console=console, refresh_per_second=12,
        ) as live:
            preflight_error = _maybe_prepare_backend_for_cli(agent, config, live)
            if preflight_error:
                live.update(Text(""))
            else:
                session.save_user(user_input, agent.messages)
            for event in agent.chat(user_input, interrupt=interrupt_evt):
                t = event["type"]

                if t == "text":
                    response_text += event["data"]
                    live.update(Markdown(response_text))

                elif t == "thought":
                    # Display thoughts in a subtle way
                    thought_text = event["data"]
                    live.update(Panel(
                        Text(thought_text, style="italic dim"),
                        title="[dim]Reasoning[/dim]", border_style="dim",
                    ))

                elif t == "tool_call":
                    d = event["data"]
                    icon = TOOL_ICONS.get(d["name"], "⚙")
                    args_fmt = "  ".join(
                        f"[dim]{k}=[/dim][cyan]{repr(v)[:60]}[/cyan]"
                        for k, v in d["args"].items()
                    )
                    live.update(Panel(
                        f"{icon}  [bold cyan]{d['name']}[/bold cyan]  {args_fmt}",
                        title="[dim]Tool Call[/dim]", border_style="cyan", expand=False,
                    ))

                elif t == "tool_result":
                    d = event["data"]
                    preview = d["result"][:500] + ("…" if len(d["result"]) > 500 else "")
                    icon = TOOL_ICONS.get(d["name"], "⚙")
                    console.print(Panel(
                        f"[dim]{preview}[/dim]",
                        title=f"[dim]{icon} {d['name']}[/dim]",
                        border_style="dim", expand=False,
                    ))
                    session.save_tool(d["name"], d["result"], agent.messages)
                    live.update(Spinner("dots2", text="  thinking…"))

                elif t == "compact":
                    d = event["data"]
                    live.update(Text(""))
                    console.print(
                        f"[dim]  ✓ Auto-compacted at turn {d['turn']} "
                        f"(every {config.compact.auto_compact_after} messages)[/dim]"
                    )

                elif t == "interrupted":
                    partial = event.get("data", "")
                    live.update(Markdown((partial or "") + "\n\n[dim]⚠ Interrupted[/dim]"))
                    console.print("[yellow]  ⚠ Interrupted.[/yellow]")
                    response_text = partial
                    break

                elif t == "error":
                    console.print(f"\n[red]Error:[/red] {event['data']}")
                    break

                elif t == "done":
                    if response_text:
                        live.update(Markdown(response_text))

        if preflight_error:
            console.print(f"\n[yellow]Backend not ready:[/yellow] {preflight_error}")
            continue

        if response_text:
            session.save_agent(response_text, agent.messages)
            msg_count += 1

    credentials.increment(sessions=1, messages=msg_count)


def _on_exit(agent, session, config, creds, msg_count):
    """Clean exit: auto-extract memories, update usage."""
    if msg_count > 1:
        console.print()
        with console.status("[dim]Saving memories…[/dim]", spinner="dots"):
            _auto_extract_memory(agent, session, config, silent=True)
    console.print(f"\n[dim]Session ID: [cyan]{session.id}[/cyan][/dim]")
    console.print("[dim]Bye![/dim]")


def _normalize_cli_command_input(user_input: str) -> str:
    stripped = (user_input or "").strip()
    lowered = stripped.lower()
    if lowered == "models":
        return "/models"
    if lowered.startswith("model "):
        return "/model " + stripped[6:].strip()
    return stripped


def _env_truthy(name: str) -> bool:
    value = (os.getenv(name) or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _llama_cpp_target(config: Config) -> str:
    parsed = urlparse(config.llama_cpp.host or "http://127.0.0.1:8081")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8081
    return f"{host}:{port}"


def _cli_backend_preflight_enabled(config: Config) -> bool:
    return config.agent.provider == "llama_cpp" and _env_truthy("APEXFORGE_CLI_BACKEND_PREFLIGHT")


def _maybe_prepare_backend_for_cli(agent: Agent, config: Config, live: Live) -> Optional[str]:
    if not _cli_backend_preflight_enabled(config):
        return None

    backend = getattr(agent, "llm", None)
    ensure_ready = getattr(backend, "ensure_ready", None)
    if not callable(ensure_ready):
        return None

    live.update(
        Spinner(
            "dots2",
            text=(
                f"  [dim]{config.ollama.model}[/dim] "
                f"starting local model server on [cyan]{_llama_cpp_target(config)}[/cyan]…"
            ),
        )
    )
    try:
        ensure_ready()
        return None
    except Exception as exc:
        return str(exc)


# ── Slash command handlers ─────────────────────────────────────────────────

def _handle_slash(cmd, arg, agent, config, profile, session, profile_name, creds):

    if cmd == "/help":
        _print_help()

    elif cmd == "/whoami":
        if creds:
            console.print(
                f"  User:    [bold]{creds['username']}[/bold]\n"
                f"  Key:     [dim]{credentials.key_short(creds)}[/dim]\n"
                f"  Machine: {creds['machine']}\n"
                f"  Plan:    [cyan]{creds['plan']}[/cyan]\n"
                f"  Sessions:{creds['usage']['sessions']}  "
                f"Messages: {creds['usage']['messages']}\n"
                f"  Config:  [dim]{credentials.CREDS_FILE}[/dim]"
            )
        else:
            console.print("[dim]No credentials.[/dim]")

    elif cmd == "/status":
        _print_status(agent, config, profile, session, creds)

    elif cmd == "/clear":
        agent.clear()
        console.print("[green]✓ Cleared.[/green]")

    elif cmd == "/compact":
        msgs = [m for m in agent.messages if m.get("role") != "system"]
        if len(msgs) < 2:
            console.print("[dim]  Nothing to compact yet.[/dim]")
            return
        with console.status("[dim]  Compacting conversation…[/dim]", spinner="dots"):
            summary = agent.compact()
        if summary:
            console.print(Panel(
                Markdown(summary),
                title="[bold dim]✓ Compacted[/bold dim]",
                border_style="dim",
                expand=False,
            ))
        else:
            console.print("[yellow]  Compact failed — history unchanged.[/yellow]")

    elif cmd == "/model":
        if not arg:
            console.print(f"Current: [bold green]{config.ollama.model}[/bold green]")
        else:
            agent.set_model(arg)
            config.ollama.model = arg
            session.model = arg
            console.print(f"[green]✓ Model → [bold]{arg}[/bold][/green]")

    elif cmd == "/models":
        models = agent.available_models()
        if not models:
            console.print(f"[yellow]Cannot reach backend '{config.agent.provider}'.[/yellow]")
            return
        for m in models:
            active = " [bold green]◀[/bold green]" if m == config.ollama.model else ""
            console.print(f"  [cyan]•[/cyan] {m}{active}")

    elif cmd == "/pull":
        if not arg:
            console.print("[yellow]Usage:[/yellow] /pull [MODEL_NAME or GGUF_URL]")
        else:
            from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}", justify="right"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(f"Pulling {arg}...", total=None)
                for event in agent.pull_model(arg):
                    st = event.get("status")
                    if st == "downloading":
                        progress.update(task, completed=event.get("completed"), total=event.get("total"))
                    elif st == "success":
                        progress.update(task, completed=100, total=100, description=f"[green]✓ Pulled {event.get('model')}")
                    elif st == "info":
                        console.print(f"[dim]  {event.get('message')}[/dim]")
                    elif st == "error":
                        progress.update(task, description=f"[red]Error: {event.get('error')}")
                        break

    elif cmd == "/del":
        if not arg:
            console.print("[yellow]Usage:[/yellow] /del [MODEL_NAME]")
        else:
            if agent.delete_model(arg):
                console.print(f"[green]✓ Deleted model:[/green] {arg}")
            else:
                console.print(f"[red]Failed to delete model:[/red] {arg} (not found or provider error)")

    elif cmd == "/skills":
        gs = agent.memory.list_global_skills()
        ps = agent.memory.list_profile_skills()
        if gs:
            console.print("[dim]Global:[/dim]")
            for s in gs: console.print(f"  [cyan]●[/cyan] {s}")
        if ps:
            console.print("[dim]Profile:[/dim]")
            for s in ps: console.print(f"  [magenta]●[/magenta] {s}")
        if not gs and not ps:
            console.print("[dim]None.[/dim]")

    elif cmd == "/memory":
        gm = agent.memory.list_global_memories()
        pm = agent.memory.list_profile_memories()
        if gm:
            console.print("[dim]Global:[/dim]")
            for m in gm: console.print(f"  [cyan]●[/cyan] {m}")
        if pm:
            console.print("[dim]Profile:[/dim]")
            for m in pm: console.print(f"  [yellow]●[/yellow] {m}")
        if not gm and not pm:
            console.print("[dim]None.[/dim]")

    elif cmd == "/reload":
        agent.reload_memory()
        console.print(
            f"[green]✓ Reloaded[/green]  "
            f"skills=[yellow]{len(agent.memory.list_skills())}[/yellow]  "
            f"memories=[yellow]{len(agent.memory.list_memories())}[/yellow]"
        )

    elif cmd == "/sessions":
        sessions = Session.list_all(profile.sessions_dir)
        if not sessions:
            console.print("[dim]No sessions yet.[/dim]")
            return
        t = Table(show_header=True, box=None, padding=(0, 2))
        t.add_column("ID", style="cyan", no_wrap=True)
        t.add_column("Started", style="dim")
        t.add_column("Model", style="dim")
        t.add_column("Turns", justify="right")
        for s in sessions[:20]:
            t.add_row(s["id"], s["created"], s["model"], str(s["turns"]))
        console.print(Panel(t, title=f"[bold]Sessions — {profile.name}[/bold]", border_style="dim"))
        console.print("[dim]  /resume SESSION_ID[/dim]")

    elif cmd == "/resume":
        if not arg:
            sessions = Session.list_all(profile.sessions_dir)
            for s in sessions[:5]:
                console.print(f"  [dim]{s['created']}[/dim]  [cyan]{s['id']}[/cyan]  {s['turns']} turns")
            if sessions:
                console.print("[dim]  Usage: /resume SESSION_ID[/dim]")
        else:
            p = profile.sessions_dir / f"{arg}.json"
            if not p.exists():
                console.print(f"[red]Session not found:[/red] {arg}")
                return
            loaded = Session(profile.sessions_dir, session_id=arg, model=config.ollama.model)
            msgs = loaded.resumed_messages
            if msgs:
                agent.load_messages(msgs)
                console.print(f"[green]✓ Resumed[/green] [cyan]{arg}[/cyan] ({loaded.turn_count} turns)")
            else:
                console.print("[yellow]No resumable messages.[/yellow]")

    elif cmd == "/history":
        n = int(arg) if arg.isdigit() else 6
        msgs = [m for m in agent.messages if m.get("role") != "system"][-n:]
        for m in msgs:
            role = m.get("role", "")
            content = str(m.get("content") or "")
            if role == "user":
                console.print(f"[bold cyan]You:[/bold cyan] {content[:300]}")
            elif role == "assistant":
                console.print(Markdown(content[:600]))
            elif role == "tool":
                console.print(f"[dim]  [{m.get('name','tool')}] {content[:120]}[/dim]")

    elif cmd == "/tokens":
        est = agent.token_estimate()
        limit = config.ollama.num_ctx
        pct = int(est / limit * 100)
        color = "green" if pct < 60 else "yellow" if pct < 85 else "red"
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        console.print(f"  [{color}]{bar}[/{color}]  [{color}]{est:,}[/{color}] / {limit:,} tokens  ({pct}%)")

    elif cmd == "/export":
        fname = arg or f"session_{session.id}.md"
        Path(fname).write_text(agent.export_markdown(), encoding="utf-8")
        console.print(f"[green]✓ Exported:[/green] {fname}")

    elif cmd == "/save":
        config.save()
        console.print("[green]✓ Config saved.[/green]")

    elif cmd in ("/profile", "/profiles"):
        _handle_profile_cmd(arg, config, profile, profile_name)

    else:
        console.print(f"[red]Unknown:[/red] {cmd}  — [cyan]/help[/cyan]")


def _print_help():
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column(style="cyan", no_wrap=True, min_width=22)
    t.add_column(style="dim")
    cmds = [
        ("/status", "Profile, session, model, token usage"),
        ("/whoami", "Show your credentials and usage"),
        ("/clear", "Clear conversation history"),
        ("/compact", "Summarize & compress conversation history"),
        ("/new", "Start a new session (saves memories first)"),
        ("/model [NAME]", "Show or switch active model"),
        ("/models", "List models from the active backend"),
        ("/pull [NAME/URL]", "Download a new model"),
        ("/del [NAME]", "Delete a model"),
        ("/skills", "List loaded skills"),
        ("/memory", "List saved memories"),
        ("/reload", "Reload .md skill/memory files"),
        ("/sessions", "List sessions for this profile"),
        ("/resume [ID]", "Resume a previous session"),
        ("/history [N]", "Show last N messages"),
        ("/tokens", "Show token usage bar"),
        ("/export [FILE]", "Export conversation as Markdown"),
        ("/save", "Save config.yaml"),
        ("/profiles", "List all profiles"),
        ("/profile new NAME", "Create a new profile"),
        ("/profile info [NAME]", "Show profile details"),
        ("/profile set model NAME", "Set profile's default model"),
        ("/help", "This help"),
        ("/exit", "Quit (saves memories automatically)"),
    ]
    for c, d in cmds:
        t.add_row(c, d)
    console.print(Panel(t, title="[bold]ApexForge Swarm — Commands[/bold]", border_style="dim", expand=False))
    console.print("[dim]  Ctrl+C during generation = interrupt only · /exit = clean exit with memory save[/dim]\n")


def _print_status(agent, config, profile, session, creds):
    est = agent.token_estimate()
    limit = config.ollama.num_ctx
    pct = int(est / limit * 100)
    color = "green" if pct < 60 else "yellow" if pct < 85 else "red"

    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column(style="dim", no_wrap=True, min_width=14)
    t.add_column()
    rows = [
        ("User", f"[bold]{creds['username']}[/bold]  [dim]{credentials.key_short(creds)}[/dim]" if creds else "–"),
        ("Profile", f"[bold magenta]{profile.name}[/bold magenta]  {profile.description}"),
        ("Provider", f"[bold cyan]{config.agent.provider}[/bold cyan]"),
        ("Model", f"[bold green]{config.ollama.model}[/bold green]"),
        ("Temperature", str(config.ollama.temperature)),
        ("Session", f"[dim]{session.id}[/dim]  {session.created_display}"),
        ("Turns", str(session.turn_count)),
        ("Tokens", f"[{color}]{est:,}[/{color}] / {limit:,}  ({pct}%)"),
        ("Skills", f"[yellow]{len(agent.memory.list_skills())}[/yellow]  (global:{len(agent.memory.list_global_skills())} profile:{len(agent.memory.list_profile_skills())})"),
        ("Memory", f"[yellow]{len(agent.memory.list_memories())}[/yellow]  (global:{len(agent.memory.list_global_memories())} profile:{len(agent.memory.list_profile_memories())})"),
    ]
    if config.agent.provider == "llama_cpp":
        rows.insert(4, ("Backend URL", f"[cyan]{config.llama_cpp.host}[/cyan]"))
        rows.insert(5, ("CLI Preflight", "enabled" if _cli_backend_preflight_enabled(config) else "disabled"))
    for k, v in rows:
        t.add_row(k, v)
    console.print(Panel(t, title="[bold]Status[/bold]", border_style="dim", expand=False))


def _handle_profile_cmd(arg, config, profile, current_name):
    if not arg:
        profiles = Profile.list_all()
        if not profiles:
            console.print("[dim]No profiles.[/dim]")
            return
        t = Table(show_header=True, box=None, padding=(0, 2))
        t.add_column("Name", style="cyan")
        t.add_column("Model", style="dim")
        t.add_column("Created", style="dim")
        t.add_column("Description", style="dim")
        for p in profiles:
            active = " [bold green]◀[/bold green]" if p.name == current_name else ""
            t.add_row(p.name + active, p.model or "(default)", p.created, p.description)
        console.print(Panel(t, title="[bold]Profiles[/bold]", border_style="dim"))
        console.print("[dim]  python main.py --profile NAME[/dim]")
        return

    sub_parts = arg.split(maxsplit=2)
    sub = sub_parts[0].lower()

    if sub == "new":
        if len(sub_parts) < 2:
            console.print("[yellow]Usage:[/yellow] /profile new NAME [description]")
            return
        name = sub_parts[1]
        desc = sub_parts[2] if len(sub_parts) > 2 else ""
        Profile.create(name, model=config.ollama.model, description=desc)
        console.print(f"[green]✓ Created:[/green] [bold]{name}[/bold]  →  python main.py --profile {name}")

    elif sub == "info":
        name = sub_parts[1] if len(sub_parts) > 1 else current_name
        if not Profile.exists(name):
            console.print(f"[red]Not found:[/red] {name}")
            return
        p = Profile(name)
        sessions = Session.list_all(p.sessions_dir)
        t = Table(show_header=False, box=None, padding=(0, 2))
        t.add_column(style="dim", min_width=12)
        t.add_column()
        t.add_row("Name", f"[bold]{p.name}[/bold]")
        t.add_row("Model", p.model or "(default)")
        t.add_row("Created", p.created)
        t.add_row("Description", p.description or "–")
        t.add_row("Sessions", str(len(sessions)))
        t.add_row("Skills", str(len(list(p.skills_dir.glob("*.md")))))
        t.add_row("Memories", str(len(list(p.memory_dir.glob("*.md")))))
        console.print(Panel(t, title=f"Profile: {name}", border_style="dim"))

    elif sub == "set":
        if len(sub_parts) < 3:
            console.print("[yellow]Usage:[/yellow] /profile set model NAME  |  /profile set description TEXT")
            return
        key, val = sub_parts[1], sub_parts[2]
        if key == "model":
            profile.update(model=val)
            console.print(f"[green]✓[/green] model → {val}")
        elif key == "description":
            profile.update(description=val)
            console.print("[green]✓[/green] description updated")
        else:
            console.print(f"[yellow]Unknown:[/yellow] {key}")
    else:
        console.print("[yellow]Usage:[/yellow] /profile new|info|set")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ApexForge Swarm")
    parser.add_argument("--profile", "-P", default="default", help="Profile name")
    parser.add_argument("--model", help="Override model")
    parser.add_argument("--resume", action="store_true", help="Resume last session")
    parser.add_argument("--session", help="Resume specific session ID")
    parser.add_argument("-p", "--prompt", help="Direct prompt — print answer and exit")
    parser.add_argument("--parallel-prompt", action="append", default=[], help="Run multiple prompts concurrently; can be used more than once")
    parser.add_argument("--multi-agent", action="store_true", help="Use the multi-agent supervisor/worker flow")
    parser.add_argument("--plain", action="store_true", help="Plain text output (no markdown, for piping)")
    args = parser.parse_args()

    from agent.config import Config
    config = Config.load()
    if args.model:
        setattr(config, "_explicit_model_override", True)
        config.ollama.model = args.model
        if config.agent.provider == "llama_cpp":
            from agent.llm_backend import LlamaCppBackend
            resolved = LlamaCppBackend(config).resolve_model_path(args.model)
            if resolved:
                config.llama_cpp.model_path = resolved

    if args.prompt:
        # Direct prompt mode — skip credential onboarding
        if args.multi_agent:
            run_parallel_prompts(config, [args.prompt], profile_name=args.profile, plain=args.plain, multi_agent=True)
        else:
            run_direct_prompt(config, args.prompt, profile_name=args.profile, plain=args.plain)
        return

    if args.parallel_prompt:
        run_parallel_prompts(
            config,
            [prompt for prompt in args.parallel_prompt if prompt.strip()],
            profile_name=args.profile,
            plain=args.plain,
            multi_agent=args.multi_agent,
        )
        return

    # Interactive mode — ensure credentials
    creds = ensure_credentials()
    run_cli(
        config,
        profile_name=args.profile,
        resume=args.resume,
        session_id=args.session,
        creds=creds,
    )


if __name__ == "__main__":
    main()

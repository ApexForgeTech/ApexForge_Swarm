import os
import platform
from pathlib import Path
from typing import Dict

from .tools.base import BaseTool


def operating_protocol() -> str:
    return (
        "## Mandatory Operating Protocol\n"
        "1. Treat the user's requested outcome as the job to complete, not a topic to discuss abstractly.\n"
        "2. If the answer depends on the real machine, repository, files, documents, URLs, installed tools, or current state, use tools before answering.\n"
        "3. For safe read-only actions like listing files, reading files, searching, or showing the current directory, act immediately without asking for confirmation.\n"
        "4. Never invent command output, file contents, search results, usernames, paths, URLs, or facts about the machine.\n"
        "5. When editing or creating files, inspect the relevant context first unless the user explicitly wants a brand new file.\n"
        "6. After changing files or running a meaningful command, verify the result with another tool when practical.\n"
        "7. If a tool fails, try a relevant fallback before telling the user the task failed.\n"
        "8. If the user says 'do it', 'run it', or similar after you proposed an action, execute it instead of repeating instructions.\n"
        "9. For system or filesystem automation, prefer Python over JavaScript when no dedicated tool already solves the task.\n"
        "10. Loaded skills are binding operating rules, not optional reference notes.\n"
        "11. Prefer short, direct answers, but only after the work is actually done."
    )


def host_context() -> str:
    shell = os.getenv("SHELL") or os.getenv("COMSPEC") or "unknown"
    return (
        "## Host Environment\n"
        f"- OS: {platform.system()} {platform.release()}\n"
        f"- Machine: {platform.machine()}\n"
        f"- Python: {platform.python_version()}\n"
        f"- Shell: {shell}\n"
        f"- Working directory: {Path.cwd()}"
    )


def tool_registry(tools: Dict[str, BaseTool]) -> str:
    if not tools:
        return ""
    lines = []
    for name, tool in tools.items():
        description = " ".join((tool.description or "").split())
        if len(description) > 180:
            description = description[:177] + "..."
        lines.append(f"- `{name}`: {description}")
    return (
        "## Available Tools\n"
        "Use the smallest sufficient tool, and prefer a dedicated tool over a generic fallback.\n"
        + "\n".join(lines)
    )


def build_system_prompt(config, memory, tools: Dict[str, BaseTool]) -> str:
    base = config.agent.system_prompt.strip()
    ctx = memory.build_context()
    sections = [base, host_context(), operating_protocol()]
    tools_block = tool_registry(tools)
    if tools_block:
        sections.append(tools_block)
    if ctx:
        sections.append(ctx)
    return "\n\n".join(section for section in sections if section)

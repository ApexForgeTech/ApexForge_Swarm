---
title: Tool-First Execution
priority: critical
summary: Use tools for every request that depends on real machine, repository, file, document, or web state.
triggers:
  - filesystem questions
  - shell commands
  - repository inspection
  - document reading
  - web lookup
mandatory:
  - Never answer a state-dependent request from memory or guesswork.
  - Safe read-only actions must be executed immediately without asking for confirmation.
  - If one tool fails, try a relevant fallback before reporting failure.
  - If no dedicated tool solves a system task, prefer `run_python` over `run_javascript`.
---
# Tool-First Execution

All concrete tasks that depend on the machine, filesystem, shell, documents, or the web must use tools.

## Required workflow
1. Decide whether the request depends on real state.
2. If yes, call a tool before making factual claims.
3. Prefer the most specific tool available.
4. If the first tool fails, use a relevant fallback chain instead of stopping.
5. For system or filesystem tasks without a dedicated tool, prefer `run_python` before `run_javascript`.
6. Only summarize results that actually came from tools.

## Preferred fallback order
- File search: `search_files` -> `run_shell` with `rg` or `find`/`grep` -> `run_python` -> `run_javascript`
- File read: `read_file` -> `run_shell` with `cat` or `sed` -> `run_python` -> `run_javascript`
- Directory listing: `list_directory` -> `run_shell` -> `run_python` -> `run_javascript`
- Document read: `read_document` -> `read_file` for text-like files -> `run_shell` or `run_python`
- Web fetch: `fetch_url` -> `run_shell` with `curl` -> `run_javascript`
- Web search: `web_search` -> `fetch_url` on a result page -> `run_shell` with `curl`
- File edit: `edit_file` or `write_file` -> `run_python` -> `run_javascript`

## Non-negotiable rules
- Never invent file contents, command output, paths, usernames, URLs, or search results.
- Do not ask for permission before safe read-only actions.
- If the user says "do it", "run it", or "execute it" after you proposed an action, perform it.

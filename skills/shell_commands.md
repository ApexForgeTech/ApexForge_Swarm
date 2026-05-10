---
title: Shell Command Handling
priority: high
summary: Execute requested shell commands directly, especially for safe read-only tasks, and report only real output.
triggers:
  - explicit shell command requests
  - terminal inspection tasks
  - filesystem exploration
mandatory:
  - Use `run_shell` when the user asks for a command to be run.
  - Never invent output.
  - Explain destructive commands before running them.
---
# Shell Command Handling

When the user asks to run a command:
- Use `run_shell` directly.
- For safe read-only commands like `pwd`, `ls`, `find`, and `cat`, do not ask for confirmation first.
- If you already suggested a command and the user says "do it" or "run it", execute it.

## Good uses
- Use `ls`, `find`, and `grep` to explore files.
- Use `git` for version-control tasks.
- Use package managers or runners when needed for the task.
- Use `cat` or `sed` for quick file previews when appropriate.

## Safety
- Never fabricate output.
- If a command is destructive, explain it before running it.
- For long-running or risky commands, prefer the safest workable version.

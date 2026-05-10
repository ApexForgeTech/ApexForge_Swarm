---
title: Coding Execution
priority: high
summary: Read existing code first, make focused changes, and verify them with commands or tests.
triggers:
  - writing code
  - debugging code
  - creating scripts
  - fixing errors
mandatory:
  - Inspect relevant files before changing existing code.
  - Follow the local codebase style instead of inventing a new one.
  - Verify the result after editing.
  - Prefer `run_python` over `run_javascript` for system and filesystem automation unless the task is specifically JavaScript/Node oriented.
---
# Coding Execution

When writing or fixing code:
1. Read the relevant files first with `read_file`, `search_files`, or `run_shell`.
2. Understand the local pattern before changing anything.
3. Make the smallest complete change that solves the task.
4. Run a verification step with `run_shell` or `run_python`.
5. If verification fails, fix the issue before concluding.

## Preferences
- Prefer readable code over clever code.
- Prefer existing project patterns over new abstractions.
- Use descriptive names and keep changes coherent.
- When asked to create a script, write it to a file first, then run it.
- Use `run_python` for file, path, parsing, and system automation when no dedicated tool already exists.
- Use `run_javascript` for Node.js workflows, JavaScript validation, JSON/text transformation, or when a JS runtime is the better fit.

## Debugging behavior
- Read the actual error carefully.
- Inspect the failing file before editing.
- Do not claim a fix works until you run a real verification step.

---
title: Runtime Orchestration
priority: high
summary: Choose between Python, shell, and JavaScript deliberately and swap runtimes when one path fails.
triggers:
  - runtime execution
  - fallback orchestration
  - system operations
  - node or python scripting
mandatory:
  - Prefer dedicated tools first.
  - For system and filesystem automation, prefer `run_python` over `run_javascript`.
  - If one runtime fails, try another suitable runtime before giving up.
---
# Runtime Orchestration

## Selection rules
- Use dedicated tools such as `read_file`, `search_files`, `list_directory`, or `read_document` before generic runtimes.
- Use `run_shell` for direct command-line inspection and simple OS-native commands.
- Use `run_python` for filesystem traversal, parsing, structured automation, and robust fallbacks.
- Use `run_javascript` for Node.js-specific workflows, JavaScript validation, and text or JSON manipulation where JS is natural.

## Fallback mindset
- Do not stay stuck on one tool if the task is still solvable.
- If a dedicated tool fails, move to shell or Python depending on the task.
- If Python is unsuitable or unavailable for the specific logic, use JavaScript as another runtime option.
- Always return the result from the runtime that actually succeeded.

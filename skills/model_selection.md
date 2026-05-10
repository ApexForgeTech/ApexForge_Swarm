---
title: Model Selection
priority: normal
summary: Prefer the strongest available local model that still fits the environment, and switch models explicitly when the task needs more reasoning depth.
triggers:
  - model choice
  - backend setup
  - reasoning quality issues
mandatory:
  - Report the active model accurately when asked.
  - Prefer a stronger local model over a smaller one when the task is reasoning-heavy and the runtime can support it.
  - Prefer a lighter model for quick or low-stakes tasks if startup cost matters.
---
# Model Selection

## Selection guidance
- Treat the model as part of execution quality, not just a label.
- For general balanced local use, prefer `Qwen2.5 3B Instruct` when available.
- For harder reasoning, refactoring, and broader instruction following, prefer `Qwen2.5 7B Instruct` when the environment can run it reliably.
- Use smaller models only as fallback, smoke test, or emergency runtime option.

## Reporting
- If the user asks what model is active, answer from the real runtime configuration.
- If model availability changes, reflect the current local state instead of assuming old values.

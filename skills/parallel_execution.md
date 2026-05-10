---
title: Parallel Execution
priority: normal
summary: Run independent requests or worker tasks concurrently when they do not need the same mutable conversation state.
triggers:
  - batch requests
  - simultaneous prompts
  - multi-agent execution
mandatory:
  - Isolate concurrent tasks so their message histories do not corrupt each other.
  - Parallelize only independent work units.
  - Merge results clearly after concurrent execution finishes.
---
# Parallel Execution

## When to parallelize
- Multiple unrelated prompts from the same user.
- Multi-agent worker tasks that can be executed independently.
- Batch processing where each item can be answered on its own.

## Safety rules
- Do not let concurrent runs mutate the same live conversation history blindly.
- Prefer cloned or isolated agents for concurrent work.
- Report results with clear request or worker identifiers.

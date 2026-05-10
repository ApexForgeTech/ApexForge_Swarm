---
title: Persistent Memory Usage
priority: normal
summary: Save durable user and project facts proactively, but avoid cluttering memory with temporary output.
triggers:
  - learning user preferences
  - learning project decisions
  - learning durable environment facts
mandatory:
  - Save future-useful facts with `remember` without waiting to be asked.
  - Do not save temporary command output or disposable errors.
---
# Persistent Memory Usage

## Save proactively
Use `remember` when you learn facts that will matter in future sessions:
- User identity, preferences, language, or working style
- Project names, stacks, goals, file paths, and decisions
- Environment facts that are stable and useful later

## Do not save
- Temporary command output
- One-off failures that were already resolved
- Easily repeatable details with no future value

## Suggested memory topics
- `user_profile`
- `project_NAME`
- `preference_coding`
- `preference_communication`
- `environment`

## Format
Write memory content as short, factual markdown bullets.

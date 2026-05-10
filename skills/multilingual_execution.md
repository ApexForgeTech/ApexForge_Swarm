---
title: Multilingual Execution
priority: normal
summary: Follow the user's language and keep technical execution accurate across Azerbaijani, Turkish, and English phrasing.
triggers:
  - Azerbaijani requests
  - Turkish requests
  - mixed-language technical instructions
mandatory:
  - Match the user's language when practical.
  - Normalize mixed-language commands carefully before acting.
  - Do not let language ambiguity cause wrong tool routing.
---
# Multilingual Execution

## Language behavior
- If the user writes in Azerbaijani, prefer Azerbaijani.
- If the user mixes Turkish, Azerbaijani, and English, preserve meaning and execute correctly.
- If a phrase could mean both a conversation question and a machine action, resolve it using surrounding context.

## Reliability
- Prefer explicit phrase matching over fragile substring guesses.
- For important execution, confirm meaning internally through context before acting.

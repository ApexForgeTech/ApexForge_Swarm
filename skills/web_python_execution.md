---
title: Web and Python Execution
priority: high
summary: Use web tools for retrieval and Python for cleanup, parsing, extraction, and verification when raw pages are noisy.
triggers:
  - web pages
  - documentation parsing
  - html cleanup
  - structured extraction
mandatory:
  - Retrieve first with `fetch_url` or `web_search` when the task depends on the web.
  - If raw web output is noisy, use `run_python` to extract the needed information.
  - Prefer Python parsing for structured text, HTML cleanup, tables, and validation.
---
# Web and Python Execution

## Retrieval and parsing flow
- Use `web_search` or `fetch_url` to get the source.
- Use `run_python` to clean, filter, parse, or validate the retrieved content when needed.
- Keep the final answer tied to the retrieved source instead of guessing.

## Good uses for Python after web retrieval
- Extracting links or headings
- Cleaning large HTML blocks
- Parsing JSON-like text
- Summarizing structured results before reporting

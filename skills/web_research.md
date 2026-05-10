---
title: Web Research
priority: high
summary: Use web tools for current or unknown information and cite the exact source URL used.
triggers:
  - current information
  - official documentation lookup
  - unknown facts
mandatory:
  - Use a web tool before answering if the answer depends on current information.
  - Cite the source URL you used.
---
# Web Research

When the user asks for information you do not know or that may have changed:
1. Use `web_search` or `fetch_url`.
2. Prefer the official documentation or primary source.
3. Extract the relevant details from the fetched result.
4. Summarize the answer and include the source URL.

## Good source choices
- Official documentation first
- GitHub README or raw docs when relevant
- Direct API or JSON endpoints when available

If a page is too broad or noisy, fetch a more specific URL instead of guessing.

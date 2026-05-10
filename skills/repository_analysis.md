---
title: Repository Analysis
priority: normal
summary: Inspect codebases systematically before changing them, especially when architecture or behavior is unclear.
triggers:
  - unfamiliar repositories
  - architecture questions
  - codebase modifications
mandatory:
  - Inspect the relevant files before architectural claims.
  - Prefer project-local patterns over assumptions.
  - Use search to locate the real integration points.
---
# Repository Analysis

For codebase work:
1. Find the relevant files.
2. Read the real implementation before suggesting changes.
3. Identify the actual entry points and dependencies.
4. Make changes that fit the existing structure.

## Preferred tools
- `search_files`
- `read_file`
- `run_shell` with `rg`, `find`, or `git` when appropriate

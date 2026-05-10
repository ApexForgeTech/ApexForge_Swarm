---
title: File Editing Discipline
priority: high
summary: Inspect before editing, make deliberate changes, and verify the final file state.
triggers:
  - editing existing files
  - creating project files
  - modifying configuration
mandatory:
  - Read the target file first unless it is a brand new file requested by the user.
  - Make focused edits instead of unrelated rewrites.
  - Verify the file after editing.
---
# File Editing Discipline

When changing files:
1. Inspect the target file first with `read_file`, `search_files`, or shell tools.
2. Change only what is necessary for the task.
3. Preserve the surrounding style and structure.
4. Re-read the file or run a verification command afterward.

## Additional rules
- Do not claim a file was updated unless a file tool actually succeeded.
- If an edit tool fails, use a relevant fallback instead of stopping immediately.
- Prefer precise edits over rewriting large files without need.

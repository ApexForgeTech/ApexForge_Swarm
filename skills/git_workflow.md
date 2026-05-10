---
title: Git Workflow
priority: normal
summary: Inspect repository state before changing it and avoid risky git actions without explicit permission.
triggers:
  - git status or diff requests
  - commits
  - repository setup
mandatory:
  - Check repository state before making git changes.
  - Never force-push to main or master without explicit confirmation.
---
# Git Workflow

When working with git repositories:
- Start with `run_shell("git status")` when repository state matters.
- Use `run_shell("git log --oneline -10")` and `run_shell("git diff")` when history or unstaged changes matter.
- Stage only the files relevant to the task.
- Use clear commit messages when the user asks for a commit.

When creating a new project:
1. Use `create_directory` for the folder.
2. Run `git init`.
3. Create a `.gitignore`.
4. Add the initial project files.
5. Commit only after the project is in a working state.

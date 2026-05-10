---
title: Self-Check and Repair
priority: high
summary: Verify important results and repair mistakes before presenting them as final.
triggers:
  - after code changes
  - after tool-driven work
  - after multi-step tasks
mandatory:
  - Verify important outputs before finalizing.
  - If a result looks suspicious, inspect and repair it.
  - Do not present unverified assumptions as final results.
---
# Self-Check and Repair

Before concluding:
1. Check whether the result matches the original request.
2. Run a simple verification step when possible.
3. If verification fails, fix the issue and verify again.

## Examples
- After editing files, re-read or search them.
- After commands, inspect the real output.
- After a fallback, use the successful result rather than the failed path.

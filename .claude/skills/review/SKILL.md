---
name: review
description: Run full code review on current changes — code quality + security
command: /review
---
Execute these steps:
1. Run the code-reviewer subagent on all new/changed files
2. Run the security-reviewer subagent on all new/changed files
3. Combine all findings into one summary grouped by severity
4. If CRITICAL or HIGH issues exist, list them clearly and wait for instructions
5. If all passed: "All reviews PASSED. Ready for testing."

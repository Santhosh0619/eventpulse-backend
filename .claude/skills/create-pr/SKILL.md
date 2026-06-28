---
name: create-pr
description: Push branch and create PR via GitHub MCP
command: /create-pr
---
1. Run: git push -u origin <current-branch>
2. Create Pull Request via GitHub MCP:
   - Title: follows commit format (e.g., feat(auth): add register and login endpoints)
   - Body:
     ## What Was Built
     - List features, endpoints, models

     ## Files Changed
     - List all new/modified files

     ## Database Changes
     - List any new tables or columns (include Alembic migration)

     ## Tests
     - List test files
     - Number of test cases
     - All passing: yes/no

     ## Checklist
     - [ ] Code review passed
     - [ ] Security review passed
     - [ ] All tests passing
     - [ ] Alembic migration verified
     - [ ] No secrets in code
   - Base: main
   - Head: current branch
3. Show the PR number and URL

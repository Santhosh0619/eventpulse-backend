---
name: commit
description: Stage all changes and commit with proper message format
command: /commit
---
1. Run: git status (show what will be committed)
2. Run: git add -A
3. Generate commit message following CLAUDE.md format: type(scope): description
4. Ask permission before committing with the generated message
5. Run: git commit -m "the message"
6. Show the commit hash

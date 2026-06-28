---
name: new-feature
description: Start next feature — switch to main, pull, create feature branch
command: /new-feature
---
1. Run: git checkout main
2. Run: git pull origin main
3. Read PROGRESS.md to identify the next feature
4. Announce what feature will be built and list all files that will be created
5. Ask permission before creating the branch
6. Run: git checkout -b feature/<feature-name>
7. Update PROGRESS.md with current status

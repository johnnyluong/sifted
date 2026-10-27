---
extends: refactoring
when: Changing structure in inertia.io without changing behavior.
---

- **Before** "Pin the behavior contract first.": Run `.claude/scripts/changes.sh start` so `/finish` can see what the refactor touches.
- **In** "Prove behavior is unchanged on the real artifact": The pin and any equivalence script run here. The smoke run on the real surface is `/finish` step 4 (`verify`).
- **Replace** "Rebase into small ordered commits.": Order the work as subtraction, then the reshape, then any follow-on cleanup, keeping the pin green after each slice. Run **Opening a PR**.

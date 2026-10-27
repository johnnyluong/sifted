---
extends: feature
when: Building new or changed behavior in inertia.io.
---

- **Before** "`how` over the affected subsystem.": Run `.claude/scripts/changes.sh start` so `/finish` can see what this change touches. It keeps an existing baseline, so a change spread over sessions keeps one.
- **In** "Delegate code-writing to a subagent": This project has no git, so there are no worktrees, branches or commits: drop `isolation: "worktree"`, `git worktree add` and "Commit liberally". File-writing delegates work in the project directory one at a time; read-only helpers may run in parallel. The brief tells the delegate to read `.claude/prompts/writing-code.md` and to list every file it wrote or deleted.
- **Replace** "Verify on the matching surface.": Verification on the real surface is `/finish` step 4 (`verify`), after the cleanup has run. Here, run the tests the delegate wrote.
- **Replace** "Rebase into small, ordered commits. Stack follow-ups.": Build in small units, running each unit's tests before starting the next. A follow-up is a separate change, started after `/finish` accepts this one.
- **In** "If the design is contested": pass `interrogate` the files from `.claude/scripts/changes.sh files`; it cannot diff against `main` here.

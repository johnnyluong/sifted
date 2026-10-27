---
name: finish
description: Finish a built change -- cleanup, every check, end-to-end verification, code review, then a report and a new baseline. This project has no git, so there is no commit, PR or merge. Run it without being asked once a feature, fix or milestone is built, unless the user asked to look at it first. Also use when asked to finish, wrap up, check, or review a change.
---

Run from the project root. Each step that changes code sends you back through the steps after it.

1. **Stop every live agent that still writes files**, then list what the change touched:
   `.claude/scripts/changes.sh files` (`diff` shows the content). That list is the scope for
   every step below. With no baseline, the scope is the files this session wrote or deleted;
   say so in the report.
2. **Clean up** when the change adds code: `/pstack:deslop`, then `/pstack:no-comments`, each
   given the changed files explicitly (both default to a diff against `main`, which does not
   exist here). Leave out generated files: `web/src/api/schema.gen.ts` and `web/bun.lock`.
   Report no-comments' encoding offers as follow-ups; do not build them now.
   Docs or tooling only: say so and skip.
3. **`.claude/scripts/check.sh`** runs ruff, the formatter check, pyright and the tests that do
   not hit live services, then the web app's checks (lockfile, API drift, typecheck, Biome,
   Vitest) and its build. Fix every failure. A failing check is never waved through.
4. **Verify it works** with the `verify` skill when a user can reach the change: a page, an API
   route, a CLI command, a bot reply. For tooling or docs only, say so and skip.
5. **`/code-review`**, passing the level every time; it otherwise reuses the last one typed.
   Target the narrowest absolute directory holding every changed file
   (`/code-review high <path>`). The first run is `high` for code, `low` for docs or tooling.
   Fix the real findings. Each follow-up run covers only the files the fixes touched, one level
   lower than the last (`high`, `medium`, then `low` until nothing is left). Report each
   finding and what you did about it, including "nothing found".
6. **`.claude/scripts/changes.sh accept`** once steps 2 to 5 are clean, so the next change
   diffs from here.
7. **Report**, written plainly (`/pstack:unslop`), with these sections, dropping any with
   nothing to say:
   - `## Why`: the problem and the approach, in one to three sentences.
   - `## What changed`: one to three bullets.
   - `## Scope`: what it covers and what it deliberately leaves out.
   - `## Verification`: checks, the end-to-end run and the review, each with its outcome.
   - `## How to try it`: the commands or clicks the user runs to see it work. At the end of a
     milestone this is required, per SPEC.md's Milestones.

Never skip the review, weaken a check, or mark a test skipped to get past a step.

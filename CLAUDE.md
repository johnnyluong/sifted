# Claude Development Notes

Rules and commands for working in this project.

## Where things are

- `SPEC.md` - the V1 spec and milestones; the source of truth
- `.claude/prompts/writing-code.md` - read before editing: library versions, stack traps, limits, how to verify
- `.claude/scripts/check.sh` - every check (ruff, format, pyright, tests)
- `.claude/scripts/changes.sh` - what a change touched, in place of git
- Skills: `/finish`, `verify`
- `.agents/playbooks/` - this project's overrides of pstack's poteto-mode playbooks

## Key technical notes

- Python 3.12 with `uv`: `uv add`, `uv run` -- never pip
- The web UI is a React SPA in `web/`, managed with bun: `bun install`, `bun run` -- never npm or pnpm
- The project root is this directory (SPEC.md's top-level `sift/`); the package is `sift/`
- Runs natively on macOS, not Docker
- M0 adds `ruff`, `pyright` and `pytest` as dev dependencies and registers the `live` pytest marker

```bash
uv run sift run                  # web app, bot, worker, scheduler in one process
uv run sift process <url>        # one URL through the pipeline
uv run sift doctor               # check ffmpeg, cookies, tokens, migrations, the web build
bun run --cwd web dev            # UI with hot reload on :5173, API proxied to a running sift run
bun run --cwd web api            # regenerate the typed client after changing an API model
.claude/scripts/check.sh         # every check
uv run pytest -m live            # opt-in end-to-end test against real services
```

## No git

This project has no git repository. That changes three things:

- `.claude/scripts/changes.sh start` snapshots the tree when a change begins; `files` and
  `diff` stand in for `git diff`, and `/finish` runs `accept` when the change passes.
- Deletes and overwrites cannot be undone, except from `.claude/baseline/`, which holds the
  files as they were when the change started.
- Without worktrees, only one session or delegate writes files at a time.

## Comments

Later sessions copy the code they find, so every long comment becomes the pattern.

- Comment only a non-obvious *why*: a constraint, a workaround, a trap. One or two lines.
- Never restate what the code does, narrate history, or list past attempts and bugs.
- Existing long comments are not a precedent; shorten one when you touch its code.

## Building

Features are built with pstack's poteto-mode, a user-scope plugin.

- New behavior, a refactor, or a bug whose cause is unknown: run `/pstack:poteto-mode` and
  follow the playbook it picks. A contained one-file change, a question, or docs: work directly.
- `.agents/playbooks/` adapts its playbooks to a project without git. Each one ends in `/finish`.
- pstack skills that diff against `main` (deslop, no-comments, interrogate) take the files
  from `.claude/scripts/changes.sh files` instead.
- pstack's driver skill is `verify`. Do not generate another verification skill.
- Build milestone by milestone, per SPEC.md: stop after each, report, and wait for confirmation.

## Checking and reviewing

**When a change is built, run `/finish` without being asked**, unless the user asked to see it
first. It runs, in order:

1. `/pstack:deslop` and `/pstack:no-comments` over the changed files, when the change adds code.
2. `.claude/scripts/check.sh`. A failing check is never waved through.
3. The `verify` skill, through every layer the change touches.
4. `/code-review`, passing the level and the narrowest directory holding the change every time:
   `high` first for code, `low` for docs or tooling, then one level lower on each follow-up.
5. `.claude/scripts/changes.sh accept`, then a report ending in how to try it.

## Development checklist

Any change a user can reach:
- [ ] Verify it end to end with `verify`, not only with tests

Schema changes:
- [ ] `uv run alembic revision --autogenerate -m "<change>"`, then read and fix the generated file
- [ ] Apply with `uv run alembic upgrade head`; test rollback with `downgrade -1` and `upgrade head` again

Code:
- [ ] Fetchers and the LLM client stay behind their interfaces, with fakes for tests
- [ ] LLM output is validated with Pydantic; prompts live in `sift/llm/prompts/`
- [ ] The SPA reaches the server only through `web/src/api` (Biome enforces it); API routes call the service layer
- [ ] Nothing logs cookies, tokens or API keys

Tests:
- [ ] Unit tests for parsing, dedup, validation, thresholds and digest selection, per SPEC.md section 11
- [ ] No test hits Instagram, Threads, Telegram or Anthropic unless marked `live`
- [ ] Frontend logic (search parsing, rail math, stage steps, the pulse, mutation policy) has Vitest tests; `web/src/api/schema.gen.ts` is generated, never edited
- [ ] Saved responses and sample media go in `tests/fixtures/`

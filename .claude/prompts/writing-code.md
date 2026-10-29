# Writing code in inertia.io

For any session or delegate writing code here: what to read first, the traps in this stack,
and how to check the result. CLAUDE.md has the workflow around it.

## Read before editing

- `SPEC.md`, the sections for the area you touch. It is the source of truth for V1.
- The installed version of a library before relying on its API (`uv.lock`, or the package
  source under `.venv/`). python-telegram-bot, SQLModel, yt-dlp and the anthropic SDK have
  all changed APIs; your training data may describe an older one.
- The `claude-api` skill before touching the Anthropic client or prompts.

## Traps in this stack

- **One process, one event loop.** The web app, bot, worker and scheduler share it. yt-dlp,
  mlx-whisper, ffmpeg and sync DB work block it; run them with `asyncio.to_thread` or a
  subprocess so the bot and web stay responsive.
- **SQLite allows one writer at a time.** The worker and the web app write concurrently; keep
  sessions short and enable WAL, or writes fail with "database is locked".
- **bun, never npm or pnpm,** for everything under `web/`: `bun install --cwd web`,
  `bun run --cwd web <script>`. Adding a package (`bun add`) is the change owner's call, like
  `uv add`.
- **TypeScript stays on `~6.0.3`.** openapi-typescript 7.13 calls the compiler API that
  TypeScript 7 no longer ships, so codegen crashes on it. It also declares `typescript ^5.x`,
  so every install prints an unmet-peer warning; that warning is expected.
- **Never edit `web/src/api/schema.gen.ts`.** Change the Pydantic model, then
  `bun run --cwd web api`. `check.sh` fails when the file and the API disagree.
- **Components never reach the server themselves.** Use `@/api`; Biome rejects imports of the
  client, the generated schema and `openapi-fetch`, and the `fetch` global, outside `web/src/api`.
- **Mutations don't invalidate.** The query client refetches every active query once any write
  settles; a hand-written `invalidateQueries` is dead weight. A form that shows its own error sets
  `meta: { quietErrors: true }` to skip the toast.
- **`sift run` serves the last build.** After changing `web/`, rebuild (`check.sh` does) or use
  `bun run --cwd web dev`.
- **New packages wait a week.** `web/bunfig.toml` sets `minimumReleaseAge`; name a range, not a
  version published in the last 7 days.
- **`@dnd-kit/react` is pre-1.0.** Keep every use of it in `web/src/components/shelf.tsx`.
- **Build pages from the shared pieces before writing markup.** `components/page.tsx` has `Page`,
  `PageHeader`, `PageSection`, `BackLink` and `Empty`; `components/ui/` has `Button`, `chipClass`,
  the fields with `Choice` and `FieldError`, `Eyebrow`, `Tag`, `Popover` and `Sheet`; the
  `surface` and `surface-pad` utilities draw a card. When a class string turns up a second
  time, make it a component there instead of copying it.

## Mistakes this project has paid for

Add one line per mistake a review or bug found, written as the rule.

- A `useMutation` fires per-call `mutate` callbacks only for its latest call; when one hook serves several calls in flight (list rows, drops), await `mutateAsync` per call.
- Phone padding pairs `env(safe-area-inset-left)` with the left side and `env(safe-area-inset-right)` with the right; never one inset on both.

## Limits

- Never read `.env`, cookie files, or anything under `data/` that holds credentials. Never log
  cookies, tokens or API keys.
- Tests never hit Instagram, Threads, Telegram or Anthropic; use the fakes behind the fetcher
  and LLM interfaces. The one live test runs only with `-m live`.
- Model names and thresholds come from config; prompts live in `sift/llm/prompts/`.
- Adding, removing or upgrading a package (`uv add`) is the change owner's call; a delegate
  reports the need instead. `uv sync` changes nothing and is always fine.

## Verify

- Everything: `.claude/scripts/check.sh`.
- One test file: `uv run pytest tests/<file> -q`.
- The web app alone: `bun run --cwd web typecheck`, `lint`, `test`, then `build`.

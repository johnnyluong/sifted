# Decisions log (prototype build, 2026-10-22)

Choices made while you were away, so you can review and reverse any of them. Architecture is in `DESIGN.md`.

## Scope and process

| Decision | Why | To reverse |
|---|---|---|
| Built milestones M0 to M6 in one pass, plus the cheap parts of M7 (retries with backoff, failure classes, stuck-job recovery, `update-tools`, README) | You asked for a prototype while away; SPEC and CLAUDE.md say to stop after each milestone | Review milestone by milestone using "How to try it" below |
| No Telegram bot; links go in through the web app (the Inbox box, Add link on every page, Cmd+V anywhere) and `POST /api/items` | You asked for this. Inbox intake (`sift/inbox/intake.py`) and the notifier seam (`sift/inbox/notify.py`) are channel-neutral, so the bot adds a channel without pipeline changes | Build `sift/inbox/telegram.py` against `intake.submit` and the `Notifier` protocol |
| Docker containers untouched | Sift runs natively (SPEC 2) and needs none; port 8000 was free. Your `yeschef` containers (3000, 8080, 5432) were left running | — |
| Design picked by an architect arena: 2 Opus designs plus an Opus judge | Your `/architect` request; the record is in `DESIGN.md` under "Synthesis decision" | — |

## Product behavior

| Decision | Why |
|---|---|
| **No API key: items wait, they don't fail.** They are downloaded and transcribed, then shown as "Waiting for LLM" | They finish on their own after you add `ANTHROPIC_API_KEY` and restart. No Retry clicks, no re-download |
| **`LLM_BACKEND=fake`** gives keyword-rule cards and scores, with a banner | It lets you click through every page without a key. Its scoring is crude on purpose; don't judge the filter by it |
| **No goals: scoring waits** ("Waiting for goals") | Scoring needs goals to mean anything; SPEC 14 says you'll enter them first |
| **Keep threshold 60, and the threshold wins** over the model's own keep/archive vote | SPEC 6. Both votes are stored (`threshold_decision`, `model_decision`) for tuning after about 20 items |
| **Override examples are true disagreements only**: your choice differs from the threshold's, newest 10 | Keeping something the filter already kept teaches nothing |
| **Digest repeat rule**: an item can appear in at most 3 digests since your last action on it. "Action" means keep, archive, done, undone, retry or reprocess, not opening the page | A literal reading of SPEC 6 never reaches the cap. Carryovers only appear as top picks |
| **Missed Sunday digest runs at startup** | If the Mac was asleep at 6pm Sunday, the next `sift run` catches up. An empty digest is never created |
| **Reprocess re-runs only the LLM** on the saved transcript and frames | Cheap, and it keeps your override. To re-download, Retry a failed item |
| **Threads video failure keeps the text** and adds a note | Text is the main Threads content; the video fetch is the most fragile path |
| **Carousels: every slide is read**, up to 10, shrunk to 1024px on the long edge. The first video slide is downloaded and transcribed; other videos count as their cover image | You asked for it (2026-10-24) after an image carousel failed. Slides are often dense text, so they keep more pixels than video frames (768px); 10 slides cost about 11k input tokens |
| **Frames spread over the whole clip** (8 at most) | A literal "every 3 s, max 8" misses overlays after 24 s |
| **Search uses SQL LIKE** over title, summary, transcript, caption, post text and on-screen text | Enough at personal scale and portable to Postgres; SPEC 13 allows it |
| **`sift run` refuses to start twice** for one `DATA_DIR` (file lock) | Two workers would claim the same items, and later two bot pollers would conflict |

## Technical

| Decision | Why |
|---|---|
| Package at `./sift` (project root), per CLAUDE.md | `uv init` put it under `src/`; it was moved |
| Pinned versions: yt-dlp 2026.10.21 (latest), anthropic 2.1.0, fastapi 0.161, sqlmodel 0.0.48, APScheduler 3.11.3, mlx-whisper 0.4.3 | `uv.lock` holds exact versions; `sift update-tools` bumps yt-dlp |
| Extra dependencies beyond SPEC: `typer` (CLI), `httpx`, `beautifulsoup4` | Each is used by exactly one module. `markdown-it-py` and `python-multipart` left with the Jinja pages |
| Structured outputs via `client.messages.parse(output_format=...)`, effort `medium` (`LLM_EFFORT`) | The SDK validates against the Pydantic models; invalid output gets one retry (SPEC 6) |
| `SCORE_MODEL` setting added (defaults to `EXTRACT_MODEL`) | Lets you score with `claude-haiku-5-5` while extracting with Sonnet |
| **Server-side refusal fallbacks not enabled** | They need the beta API surface and don't apply to Haiku. A refusal fails the item with "The model declined" (not retried). Worth turning on if refusals show up |
| `DIGEST_CRON` must name weekdays (`SUN`, `MON-FRI`); numbers are rejected at startup | APScheduler 3 counts weekdays from Monday, so cron's `0` would fire on Monday |
| Cross-site writes are refused (`Sec-Fetch-Site`, falling back to the Origin header), with a JSON 403 | Any website open in your browser could otherwise drive the localhost app and spend API credit. Fetch Metadata survives a dev proxy that rewrites Host |
| Instagram and Threads share links are resolved when you paste them, so a share link and the post's own link dedup | The answer ("Already saved") arrives at once. Offline, the link queues as is and the fetch stage resolves it; if the post was already saved, the share item is removed. Imports keep share links unresolved until fetch, so the drip stays paced |
| Images sent to Claude are typed by their bytes, not their file extension | CDNs sometimes serve WebP or PNG under a `.jpg` name |
| Whisper model `mlx-community/whisper-large-v3-turbo` already downloaded (~1.6 GB, in `~/.cache/huggingface`) | Saves the wait on your first reel |
| Web UI: a React SPA in `web/` (bun, Vite, TanStack Router and Query, Tailwind v4, dnd-kit, Motion), fonts self-hosted | Built to `web/dist` and served by FastAPI, so the app works offline and stays one process. `check.sh` builds it |
| No auth or CSRF | Binds to 127.0.0.1. **Add both before exposing it over Tailscale** |


## Web UI rebuild (2026-10-23)

The Jinja and HTMX pages were replaced by a React SPA. Two designs competed in an arena; the second ("brass and steel") won 29 to 22 and took grafts from the first. `DESIGN.md` has the shape under "Web UI".

| Decision | Why |
|---|---|
| **Base: the server-computed pulse, a hand-written `web/src/api`, `write_allowed` on Fetch Metadata, `spa.py`** | The pulse also catches scheduled digests and actions from other channels, and its `busy` ignores retry backoff |
| **Grafted: a global error toast with a `meta.quietErrors` opt-out; invalidation on settle, not success; `setQueryData` from item actions** | A 409 still redraws the screen, and forms that show their own errors don't toast twice |
| **Grafted: outcome toasts from `StatusView.in_motion`** ("Kept: <title>, 86" with Open, "Archived: <title>" with Keep anyway) | You see where a link landed without watching the Inbox |
| **Grafted: `SubmitBody.channel`** (`web` or `api`, default `api`); the SPA sends `web` | Pastes from the web app stay recorded as web, as the old pages did |
| **Grafted: dates in the server's `TIMEZONE`** (`StatusView.timezone`) | They agree with the digest schedule when you read from another time zone |
| **Grafted: an override drawn as a dashed tether across the line** | A kept-anyway item reads as a crossing, without a badge |
| **Grafted: `[data-theme]` light and dark override, a JSON 403, `parseId` on id routes, `fileURLToPath` in configs** | Small correctness fixes from the losing design |
| **A way to add a link on every page**: the Inbox box, Add link in the sidebar (Add on the phone tab bar), and Cmd+V outside a text field | The README promised a paste box on every page |
| **`/` goes to Goals until a goal is active**, then to the Inbox | Before, any goal (even an inactive one) counted |
| **Dependencies**: `markdown-it-py` and `python-multipart` removed; `jinja2` kept for the LLM prompts; `web/` packages from the winning design, resolved under `bunfig.toml`'s 7-day `minimumReleaseAge` | A new npm release waits a week before it can install |
| **TypeScript pinned `~6.0.3`; Biome instead of ESLint and Prettier** | openapi-typescript 7.13 crashes on TypeScript 7; Biome is one binary and holds the import fence |
| **No optimistic updates, no SSE, no client store, no code splitting** | One user on localhost: a refetch takes 10 to 30 ms, and the pulse revision is what a later push channel would send |

## Import saved posts (M1, 2026-10-23)

An arena picked the design (candidate 1 as the base, with grafts from candidate 2). `DESIGN.md` has the shape under "Import".

| Decision | Why |
|---|---|
| **The export is read by path, not by key names.** A file counts only when a path token is `saved` and the path has no `messages` or `inbox` token; every string in it goes through the paste box's URL parser | Meta's export schema is undocumented and changes. DM folders are named after the other account, so a folder like `saved_by_grace_1` must not count |
| **A preview first; nothing reaches Instagram until you start** | The preview shows saved, already in Sift, can't read, and new, with the cost and the hours |
| **One imported post in flight, about every 3 minutes, at most 100 a day** (`IMPORT_GAP_SECONDS`, `IMPORT_DAILY_CAP`) | No burst on the secondary account. The next release time is stored, so a Mac waking from sleep releases one post, not a backlog |
| **Auto-pause after 5 failed downloads in a row** | Old saves are often deleted; 5 in a row at a 15% deletion rate is about 1 in 13,000, so a pause means a login wall or a rate limit |
| **Deleted or private posts fail at once, for every source** | Retrying a dead post costs 4 fetches over about 30 minutes |
| **Failed items can be archived** | A big import's dead links can be cleared from the Inbox. An archived post that was never scored offers only Reprocess, so an empty card cannot reach Kept or the digest |
| **Imported posts are quiet**: no toast or notifier call per post | A 15-hour import would otherwise toast every 3 minutes |
| **The zip is the raw request body** (`application/zip`) | No multipart parser, so `python-multipart` stays out |

## Organization (M2 backend, 2026-10-24)

The same arena picked the design. `DESIGN.md` has the shape under "Organization".

| Decision | Why |
|---|---|
| **One Haiku 5.5 outline call per post, outside the pipeline** (gist, key points, labels, topic) | The extract and score contracts stay as they are, and the backlog is organized for $0.0008 a post with no re-extract |
| **Briefs on Haiku 5.5, rewritten when a topic settles** (30 minutes quiet, a day at most during an import, or at once on request) | A Sonnet rewrite per settled change would cost about as much as reading the post |
| **Folds only when the brief cites every key point of a post** | A point the model forgot keeps the post visible instead of hiding it |
| **Merges are suggestions you confirm**, never automatic; a dismissed suggestion does not return | A wrong automatic merge has no undo |
| **The first shelves come from a batch of up to 25 posts** | Shelving the backlog one post at a time makes topics too narrow |
| **A removed topic's name is not reused** | Otherwise the next post would recreate it |

## Setup, prompt boundary and digest refill (2026-10-25)

An arena picked the design (candidate B as the base, with candidate A's caps, old-digest parse and question set). `DESIGN.md` has the shape under "Setup, prompt boundary and digest queue".

| Decision | Why |
|---|---|
| **First run is 7 questions**, then Claude drafts goals and values, and you edit the draft before anything is saved | A bare goal form asked you to name goals cold; the questions ask about what you actually save |
| **The draft runs on `DIGEST_MODEL`** (Sonnet), about $0.01 a draft | It writes for you, as the digest does; no new setting |
| **Redo setup only adds, revives or updates goals**; a drafted goal names the current goal it rewrites by id (`revises`), which updates that goal in place; a goal you named as a focus is never folded into another; it turns off only the goals you uncheck, and never leaves none active | An omitted goal must never retire by accident, and overlapping goals split one outcome's posts; matching by exact title failed when the model shortened a title, which left a near-duplicate beside the original |
| **Your answers are saved when you save the goals**, and prefill the next redo | The draft stays stateless, so "nothing is saved before review" holds |
| **How strict to be shapes the values text**, not the keep threshold | The threshold stays one calibrated number in config |
| **No rescore after setup** | New goals apply to new posts and to posts waiting for goals; a rescore is the next roadmap step |
| **Untrusted text cannot close a prompt tag**, every system prompt says tagged text is data, and every LLM text field is capped | One boundary in the template engine and the schemas, which tests prove for every prompt, instead of care in each template |
| **"Open link" appears only for a link the post states** (caption, post text or transcript) | A post could otherwise steer the card to any site; on-screen text is the model's own reading, so it is not evidence |
| **The digest is stored as data, not markdown**, and rendered as plain text with Sift links only | Picks need structure for Done, and markdown let a title turn into an outside link or image |
| **A done or archived pick is replaced by the next post in the digest's own order**, worked out when the page loads | Nothing is written on Done, so Undo, reprocess and every channel just work |
| **A carryover that moves up does not count toward the 3-digest limit** | Counting it would need a write on every read |
| **The 2 old digests were converted**, keeping their opening, picks, reasons and lines | Their markdown was ours, so it reads back exactly |
| **`react-markdown` removed** | Nothing renders markdown any more |

## Not verified (needs you)

- **Live Instagram and Threads fetches were not run.** They need the secondary account's browser cookies, and reading Chrome cookies brings up a Keychain prompt on your Mac. Run `uv run sift doctor` first, then `uv run sift process <one reel url>`.
- **The real Anthropic call was not run**, because there is no key. The SDK call shape was checked against the installed SDK source, and fakes cover the pipeline.
- **The Threads oEmbed parser was tested against a hand-built fixture**, not a captured response. If Meta's HTML differs, the fallback reads the page's `og:description`. Save a real response into `tests/fixtures/threads_oembed.json` once you have one.
- What *was* verified:
  - 81 tests pass (store, pipeline, digest, web, schemas, logging redaction, and real ffmpeg on a generated clip).
  - mlx-whisper transcribed a generated speech clip on the worker thread.
  - Every page was clicked through in a real browser, in light and dark mode and at phone width.

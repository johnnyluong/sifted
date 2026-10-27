# Sift: Project Spec (V1)

Working name: **Sift**. Rename freely.

This document is the source of truth for V1. Read it fully before writing code. Build milestone by milestone (see "Milestones"), stop at the end of each one, summarize what was built and how to test it, and wait for confirmation before starting the next. If something in this spec is ambiguous or turns out to be wrong in practice, ask rather than guess.

---

## 1. What we're building

A personal tool that turns saved social media content into something I actually use.

I scroll Instagram and Threads and find useful things: restaurants and places to visit, recipes, marketing and business strategies, creative ideas from technologists. I save them but never revisit them. Sift fixes that.

**Core loop:**
1. I define my goals and values once (personal, professional, entrepreneurial).
2. I share an Instagram reel or Threads post link to a Telegram bot.
3. Sift downloads the content, transcribes it, reads on-screen text, and extracts the core knowledge into a structured card (a place, a recipe, a step-by-step playbook, an idea).
4. Sift scores the card against my goals. Relevant items are **Kept**, noise is **Archived** (never deleted).
5. A weekly **digest** tells me what's worth acting on now, tied to my goals.
6. A local web app lets me browse, search, override decisions, and mark things **Done**.

**What matters most:** filtering out noise and the actionable digest. Extraction quality is necessary but not the product by itself.

**V1 is for one user (me), running locally on my Mac.** No auth, no multi-tenancy, no deployment. Keep the code clean enough that it can become a real product later, but do not build for that now.

---

## 2. Decisions already made

| Area | Decision | Why |
|---|---|---|
| Language | Python 3.12, managed with `uv` | yt-dlp and mlx-whisper are native Python; one language for the whole V1 |
| Web | FastAPI JSON API, plus a React SPA in `web/` (React 19, Vite, TypeScript, bun) that FastAPI serves from `web/dist` | One process, one URL. The SPA uses only `/api/`, so a mobile app can use the same API |
| Database | SQLite via SQLModel, migrations with Alembic | Zero ops. Keep queries ORM-based so moving to Postgres later is a config change |
| Inbox | Telegram bot using **long polling** (python-telegram-bot) | No public URL or tunnel needed. Phone share sheet goes straight to the bot |
| Background jobs | A simple job queue backed by the `items` table, processed by an asyncio worker in the same process | No Redis/Celery for V1 |
| Video download | `yt-dlp` (pin a version, make updating easy) | Best maintained Instagram extractor |
| Threads | Text via Meta's public Threads oEmbed endpoint; video via a cookie-authenticated fetch (see section 5) | yt-dlp core has no Threads extractor |
| Transcription | `mlx-whisper` (Apple Silicon), model configurable | Fast and free locally |
| Frames | `ffmpeg` (installed via Homebrew) | Sample frames for on-screen text |
| LLM | Anthropic API via the `anthropic` Python SDK | Extraction, scoring, digest |
| Runtime | **Native on macOS, not Docker** | Docker can't use Metal (mlx-whisper) and can't read browser cookies for yt-dlp |

LLM model names must come from config, not be hardcoded. Defaults:
- `EXTRACT_MODEL=claude-sonnet-5-5` (needs vision for frames)
- `DIGEST_MODEL=claude-sonnet-5-5`
- I may want to test `claude-haiku-5-5` for cost, so keep this easy to swap.

---

## 3. Architecture

```
Phone share sheet
      |
      v
Telegram bot (long polling) --> items table (status=queued)
                                     |
                                     v
                              Worker (asyncio loop)
                                     |
             +-----------------------+------------------------+
             |                       |                        |
        Fetcher (by source)    Media processing          LLM pipeline
        - instagram (yt-dlp)   - mlx-whisper transcript   - extract card
        - threads (oEmbed +    - ffmpeg frames            - score vs goals
          cookie fetch)        - thumbnail                - keep/archive
             |                       |                        |
             +-----------------------+------------------------+
                                     |
                                     v
                                SQLite DB  <---- FastAPI web app (localhost)
                                     |
                                     v
                       Weekly digest --> Telegram message + digest page
```

Suggested layout:

```
sift/
  pyproject.toml
  .env.example
  alembic/
  sift/
    config.py          # pydantic-settings, reads .env
    db.py              # engine, session
    models.py          # SQLModel tables
    bot/               # telegram handlers
    worker/            # job loop, retries
    fetchers/          # base.py, instagram.py, threads.py
    media/             # transcribe.py, frames.py
    llm/               # prompts/, extract.py, score.py, digest.py
    web/               # JSON API, SPA serving
    digest/            # scheduling + rendering
  web/                 # the React SPA (bun); builds to web/dist
  data/                # gitignored: sqlite db, media, cookies
  tests/
    fixtures/          # saved oEmbed responses, sample transcripts, short sample video
```

---

## 4. Data model

**goals**
- `id`, `title`, `description` (why it matters, what I'm working toward), `category` (personal / professional / entrepreneurial / other), `active` (bool), `created_at`, `updated_at`

**values** (single row or simple text blob is fine)
- free text describing what I care about and what counts as noise for me

**items**
- `id`, `source` (instagram / threads), `url` (as received), `canonical_id` (shortcode, unique, used for dedup)
- `status`: `queued` | `fetching` | `processing` | `kept` | `archived` | `done` | `failed`
- `status_reason` (short text, e.g. why archived or why failed)
- `attempts`, `last_error`
- `author_handle`, `caption`, `post_text` (Threads), `transcript`, `ocr_text`
- `media_path` (optional, may be deleted after processing), `thumbnail_path`
- `item_type`: `place` | `recipe` | `playbook` | `idea` | `product` | `other`
- `title`, `summary` (2 to 3 sentences), `details` (JSON, shape depends on type, see below)
- `next_action` (one concrete thing I could do)
- `relevance_score` (0 to 100), `matched_goal_id` (nullable), `relevance_reason`
- `user_override` (nullable: `keep` / `archive`), `received_at`, `processed_at`, `done_at`

**digests**
- `id`, `period_start`, `period_end`, `content_md`, `item_ids` (JSON), `sent_at`

**`details` JSON by type** (validate with Pydantic models):
- `place`: name, neighborhood/city, address if stated, kind (restaurant, bar, park...), why it's notable, what to order/do, price hints, maps search query
- `recipe`: dish, ingredients (with amounts if stated), steps, time, notes
- `playbook`: goal of the tactic, steps (ordered), tools mentioned, examples, caveats
- `idea`: the core idea, who made it, how it could apply to my goals
- `product`: name, what it is, price if stated, link if stated
- `other`: key points

Rules for extraction: only include facts actually present in the caption, transcript, post text, or frames. Never invent addresses, amounts, or steps. Use `null` for unknown fields.

---

## 5. Ingestion details

### Telegram bot
- Only accept messages from `TELEGRAM_ALLOWED_CHAT_ID`. Ignore everyone else silently.
- Extract all URLs from the message text. Supported patterns:
  - Instagram: `instagram.com/reel/{code}`, `instagram.com/reels/{code}`, `instagram.com/p/{code}` (treat `/p/` as best effort, see below)
  - Threads: `threads.com/@{user}/post/{code}`, `threads.com/t/{code}`, and the legacy `threads.net` versions
- Strip tracking params (`igsh`, `utm_*`, etc.) before computing `canonical_id`.
- Dedup on `canonical_id`. If already present, reply with its current status instead of reprocessing.
- Reply immediately: "Got it, processing."
- When processing finishes, reply with a short result:
  - Kept: title, type, matched goal, next action. Inline buttons: **Archive**, **Open**.
  - Archived: title and one-line reason. Inline button: **Keep anyway**.
  - Failed: short reason and a hint (e.g. "yt-dlp may need updating: `uv run sift update-tools`").
- Commands: `/status` (queue counts), `/digest` (generate digest now), `/goals` (list active goals).

### Instagram fetcher
- Use the yt-dlp Python API (not a subprocess) with `cookiesfrombrowser` set from config (browser name and optional profile). Cookies should come from a **secondary Instagram account**, not my main one.
- Pull: video file, caption, author handle, thumbnail.
- Pace requests: one Instagram fetch at a time, with a configurable delay between fetches.
- `/p/` posts (images/carousels): V1 stores caption and thumbnail only and runs extraction on the caption. Mark `status_reason` accordingly. Don't spend time on full carousel support yet.

### Threads fetcher
1. **Text first:** call Meta's public oEmbed endpoint `https://graph.threads.net/v1.0/oembed?url=<post_url>` (no token needed for public posts). Parse the returned `html` blockquote with BeautifulSoup to get the post text and author.
2. **Video if present:** if the post contains video, fetch it with a cookie-authenticated request (same browser cookies approach, Threads domain only). The page needs a logged-in session and browser-like headers; media URLs are in JSON embedded in the page. Alternatively try the third-party `yt-dlp-threads` plugin first and fall back to the manual approach. Isolate this behind the fetcher interface since it's the most likely thing to break.
3. Known limitation: oEmbed covers a single post, not a multi-post thread. V1 accepts this; note it in `status_reason` if the post looks like part of a thread.

### Fetcher interface
```python
class Fetcher(Protocol):
    def matches(self, url: str) -> bool: ...
    def canonical_id(self, url: str) -> str: ...
    async def fetch(self, url: str, workdir: Path) -> FetchResult: ...
```
`FetchResult` holds: author, caption/post_text, video_path (optional), thumbnail_path (optional), raw metadata JSON.

### Media processing
- Transcribe audio with mlx-whisper. Model configurable (`WHISPER_MODEL`, default a small/turbo model).
- Extract frames with ffmpeg: about 1 frame every 3 seconds, max 8 frames, downscaled to roughly 768px on the long edge. These go to the LLM as images for on-screen text (recipes and playbooks often live in text overlays).
- After successful processing, delete the video if `KEEP_MEDIA=false` (default). Always keep the thumbnail.

---

## 6. LLM pipeline

Keep prompts in `sift/llm/prompts/` as separate files, not inline strings, so I can iterate on them.

### Step 1: Extract
Input: source, author, caption/post text, transcript, frames (images).
Output (strict JSON, validated with Pydantic, retry once on invalid JSON): `item_type`, `title`, `summary`, `details`, `next_action`.

### Step 2: Score
Input: the extracted card, my values text, active goals, and up to 10 recent examples where I overrode a decision (with my override). The overrides are how the filter learns my taste.
Output: `relevance_score` (0 to 100), `matched_goal_id` or null, `relevance_reason` (one sentence), `decision` (`keep` / `archive`).
Threshold: `KEEP_THRESHOLD` in config (default 60). The model's decision and the threshold should agree; if they don't, trust the threshold and log it.

Steps 1 and 2 can be one API call if it's simpler, but keep the outputs separate in code.

### Step 3: Digest (weekly)
Input: items kept since the last digest that are not `done`, plus older kept items not yet surfaced in any digest, grouped by goal.
Output (markdown):
- **Top 3 to act on this week**, each with why (tied to a goal) and the concrete next action
- **By goal:** short bullets for the rest
- **Places:** grouped by neighborhood/city
- Never resurface items marked `done`. Don't repeat an item in more than 3 digests unless I interact with it.

Schedule: weekly, configurable day and time (default Sunday 6pm America/New_York), using APScheduler in-process. Send to Telegram (split if over message length limits) and store in `digests`.

---

## 7. Web app (localhost)

Pages:
- **Goals:** first-run onboarding if no goals exist. Add, edit, deactivate goals; edit values text.
- **Inbox:** items being processed or failed, with retry button.
- **Kept:** cards grouped or filterable by goal and type. Search across title, summary, transcript.
- **Archived:** same view, with **Keep** button and the archive reason visible.
- **Item detail:** thumbnail, original link, extracted card, transcript (collapsed), score and reason, buttons: Keep / Archive / Done / Reprocess.
- **Digests:** list and detail.

Every override (Keep on an archived item, Archive on a kept item) is stored in `user_override` and feeds the scoring examples.

Design: clean, mobile-friendly, readable cards. Function over polish for V1.

JSON API under `/api/` mirroring the above (list items with filters, get item, update status, CRUD goals, list digests). The web app is a React SPA that calls only this API, so a mobile app can use it as is.

Note: I'll access the web app from my phone over Tailscale later. Bind host should be configurable (`127.0.0.1` default).

---

## 8. Config (.env)

```
ANTHROPIC_API_KEY=
EXTRACT_MODEL=claude-sonnet-5-5
DIGEST_MODEL=claude-sonnet-5-5
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_ID=
COOKIES_BROWSER=chrome
COOKIES_BROWSER_PROFILE=
WHISPER_MODEL=
KEEP_THRESHOLD=60
KEEP_MEDIA=false
FETCH_DELAY_SECONDS=20
DIGEST_CRON=0 18 * * SUN
TIMEZONE=America/New_York
WEB_HOST=127.0.0.1
WEB_PORT=8000
DATA_DIR=./data
```

`.gitignore` must include `.env`, `data/`, and any cookie files. Never log cookies, tokens, or API keys.

---

## 9. Running it

- `uv run sift run`: starts web app, Telegram bot, worker, and scheduler in one process.
- `uv run sift process <url>`: process a single URL from the CLI (useful for testing without Telegram).
- `uv run sift digest`: generate a digest now.
- `uv run sift update-tools`: update yt-dlp (and the Threads plugin if used) and print versions.
- `uv run sift doctor`: check ffmpeg, cookies readable, Telegram token valid, Anthropic key valid, DB migrated.

README must cover: Homebrew deps (`ffmpeg`), creating the Telegram bot with BotFather, finding my chat ID, setting up the secondary Instagram account's cookies, and running with launchd later (optional, not required for V1).

---

## 10. Reliability

- Worker retries failed items up to 3 times with backoff. After that, `failed` with a readable reason, and notify me on Telegram.
- Classify failures: `download_failed` (likely yt-dlp/cookies), `transcription_failed`, `llm_failed`, `unsupported_url`. The Telegram failure message should suggest the likely fix.
- On startup, reset any items stuck in `fetching`/`processing` back to `queued`.
- Log to `data/logs/` with rotation.

---

## 11. Testing

- Unit tests for URL parsing, canonical IDs, dedup, oEmbed HTML parsing (use saved fixture responses), Pydantic validation of LLM outputs, threshold logic, digest selection rules.
- Fetchers and the LLM client behind interfaces with fake implementations for tests. Tests must not hit Instagram, Threads, or the Anthropic API by default.
- One opt-in integration test (`-m live`) that processes a real URL end to end.

---

## 12. Milestones

Stop after each milestone, summarize, and tell me how to verify it.

- **M0: Scaffold.** uv project, config, DB models, Alembic, `sift doctor`, empty web app with a health page, test setup.
- **M1: Inbox.** Telegram bot (allowed chat only), URL parsing, dedup, items queued, `/status`. `sift process <url>` queues too.
- **M2: Instagram ingestion.** yt-dlp fetch with browser cookies, transcription, frames, thumbnail. Results stored on the item. No LLM yet.
- **M3: Threads ingestion.** oEmbed text, video fetch when present.
- **M4: Extraction and scoring.** Prompts, structured outputs, keep/archive, Telegram result messages with inline buttons.
- **M5: Web app.** Goals onboarding, Inbox, Kept, Archived, item detail, overrides, search.
- **M6: Digest.** Weekly schedule, Telegram delivery, digest pages, `/digest` and `sift digest`.
- **M7: Hardening.** Retries, failure classification, stuck-job recovery, `sift update-tools`, README.

---

## 13. Out of scope for V1

- Multi-user, auth, hosting, billing
- Native mobile app
- Slack inbox (Telegram only for now; keep the inbox layer modular so Slack can be added)
- Full Instagram carousel/image support, full multi-post Threads threads
- TikTok, YouTube, X (fetcher interface should make these easy later)
- Embeddings/semantic search (plain SQLite FTS5 is fine if search needs to be better than LIKE)

---

## 14. Open questions to confirm with me before M4

1. Starting goals and values text (I'll enter these in the Goals page or give them to you directly).
2. Whether the keep threshold of 60 feels right after the first ~20 items.
3. Digest day and time.

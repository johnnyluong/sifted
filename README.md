# Sift

Sift turns saved Instagram reels and Threads posts into structured cards, such as a place, a recipe, a playbook or an idea. It scores each card against your goals, keeps what matters, archives the noise, and writes a weekly digest of what to act on.

It runs locally on your Mac as one process: a web app, a background worker and a digest scheduler.

## Requirements

- macOS on Apple Silicon (mlx-whisper needs Metal)
- [uv](https://docs.astral.sh/uv/)
- ffmpeg: `brew install ffmpeg`
- An Anthropic API key, for real extraction and scoring
- [bun](https://bun.sh) 1.4 or later, to build the web app: `brew install oven-sh/bun/bun`

## Quick start

```bash
uv sync
cp .env.example .env          # add ANTHROPIC_API_KEY
bun install --cwd web && bun run --cwd web build   # the web app; sift run serves web/dist
uv run sift doctor            # checks ffmpeg, cookies, the key, the whisper model, the database, the web build
uv run sift run               # http://127.0.0.1:8000
```

On first run, the app opens on setup. Answer a few questions, edit the goals and values Sift drafts from them, and save. Then add a reel or Threads link: paste it into the box on the Inbox, use **Add link** in the sidebar (the **Add** tab on a phone) from any page, or press Cmd+V anywhere outside a text field.

To try the app without an API key, set `LLM_BACKEND=fake` in `.env`. Cards and scores then come from keyword rules instead of Claude, and a banner says so.

With no key and no fake backend, links are still downloaded and transcribed. They wait in the Inbox as "Waiting for LLM" and finish on their own once you add a key and restart.

## Commands

| Command | What it does |
|---|---|
| `uv run sift run` | Web app, worker and weekly digest in one process. Refuses to start twice for the same `DATA_DIR`. |
| `uv run sift process <url>` | Processes one link. Runs the pipeline in this process, or hands the link to a running `sift run` and waits. Exit code 0 means kept or archived, 1 failed, 2 waiting. |
| `uv run sift import <zip> [--limit N] [--yes]` | Previews the saved posts in a Meta export, then starts importing them (all, or the newest N). The running `sift run` sends them to the pipeline one at a time. |
| `uv run sift digest` | Writes a digest now and prints it. |
| `uv run sift doctor` | Checks setup. Pass `--no-cookies` to skip the browser cookie read, which can show a Keychain prompt. |
| `uv run sift update-tools` | Upgrades yt-dlp to its latest release. Run this when Instagram downloads start failing. |

## Instagram cookies (secondary account)

Instagram needs a logged-in session to download reels. Use a secondary account, not your main one:

1. Create a separate browser profile, or use a browser you don't use day to day, and log in to Instagram there with the secondary account. Also log in to threads.com for Threads videos.
2. Set `COOKIES_BROWSER` (`chrome`, `firefox`, `safari`, `brave`, `edge`) and `COOKIES_BROWSER_PROFILE` (for Chrome, the profile folder name, such as `Profile 2`) in `.env`.
3. Run `uv run sift doctor`. The first cookie read from Chrome asks for Keychain access to "Chrome Safe Storage". Choose **Always Allow**, or the background worker cannot read cookies later.

Instagram fetches are spaced `FETCH_DELAY_SECONDS` apart (default 20).

## Import what you saved before Sift

Sift can bring in the posts you saved on Instagram and Threads before you started using it.

1. In Instagram, open **Accounts Center > Your information and permissions > Download your information**.
2. Choose **Some of your information**, tick **Saved**, and pick format **JSON** and date range **All time**.
3. Wait for Meta's email, then download the zip. It usually takes a few hours.
4. Open **Import** in the sidebar and drop the zip, or run `uv run sift import ~/Downloads/<file>.zip`.
5. Read the preview: how many saved posts the zip holds, how many are already in Sift, how many links Sift can't read, and what the rest cost and how long they take. Choose **Newest 50**, **Newest 100**, **All**, or type your own number, then start.

Sift reads only the files for saved posts (never likes, views or messages) and deletes the zip once it has read it. Imported posts go to Instagram from your secondary account one at a time: about every `IMPORT_GAP_SECONDS` (default 180, jittered), at most `IMPORT_DAILY_CAP` a day (default 100), and never two at once. A link you paste waits behind one imported post at most. Imported posts are not announced one by one; the Inbox shows one line while an import runs, and imported rows carry an **Imported** chip.

The import pauses itself after 5 imported posts in a row fail to download. Run `uv run sift doctor`; if the account is fine, the posts were likely deleted, so resume. A post that is deleted or private fails at once instead of retrying. Archive it from its page to clear it from the Inbox.

Settings: `IMPORT_GAP_SECONDS` (keep it at or above `FETCH_DELAY_SECONDS`), `IMPORT_DAILY_CAP`, and `IMPORT_MAX_BYTES` (the largest upload, default 2 GiB).

## Topics and briefs

Sift sorts what you keep into topics, so you read a topic once instead of every post.

- **Each post** gets a one-line gist, up to five key points, a few labels (such as `date night` or `search console`) and a topic. This happens in the worker's idle time, a minute or so after the post is scored. Posts saved before topics existed are organized the same way, newest first, once you upgrade.
- **Each topic** with two or more kept posts gets a brief: the posts' key points merged into short sections, each point numbered back to the posts that make it. A brief is rewritten 30 minutes after its posts stop changing (once a day while an import runs). **Update now** on the topic page rewrites it at once.
- **A post that adds nothing new** folds under the post that covers it ("Covered by"). It folds only when the brief cites every one of its key points. Nothing is hidden for good: archive the cover, or move the post, and it unfolds.
- **You stay in charge of the shelves.** Move a post to another topic from its page, and Sift learns from your moves. Rename, merge or remove a topic from its page. Sift suggests merging two topics that look like one shelf ("Merge X into Y?"), but never merges on its own. A removed topic's posts are placed elsewhere, and its name is not reused.

Settings: `OUTLINE_MODEL` (default `claude-haiku-5-5`) writes the gists, key points, labels and topic picks, and suggests merges. `BRIEF_MODEL` (default `claude-haiku-5-5`) writes the briefs. Organizing costs about $0.0008 per post and $0.002 to $0.004 per brief on Haiku 5.5.

## Telegram (not built yet)

The Telegram bot is not built yet; for now, paste links in the web app. The inbox and notification seams are ready for it (`sift/inbox/`). When it is added, setup is:

1. Message [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token into `TELEGRAM_BOT_TOKEN`.
2. Send your bot any message, then open `https://api.telegram.org/bot<token>/getUpdates` and copy `message.chat.id` into `TELEGRAM_ALLOWED_CHAT_ID`.

## Data

Everything lives under `DATA_DIR` (default `./data`):

- `sift.db`: the SQLite database. `sift run` applies migrations on start.
- `media/<item id>/`: thumbnails, carousel slides and frames. Videos are deleted after processing unless `KEEP_MEDIA=true`.
- `imports/`: an uploaded export while it is being read. The file is deleted right after.
- `logs/sift.log`: rotating logs. Secrets are redacted.

## Running in the background with launchd (optional)

Save this as `~/Library/LaunchAgents/com.sift.plist`, with the paths adjusted, then run `launchctl load ~/Library/LaunchAgents/com.sift.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.sift</string>
  <key>WorkingDirectory</key><string>/Users/you/Projects/inertia.io</string>
  <key>ProgramArguments</key><array><string>/Users/you/.local/bin/uv</string><string>run</string><string>sift</string><string>run</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
```

## Development

```bash
.claude/scripts/check.sh                          # ruff, format, pyright, tests, then the web app's checks and build
bun run --cwd web dev                             # http://localhost:5173 with hot reload; needs sift run on :8000
bun run --cwd web api                             # regenerate web/src/api/schema.gen.ts after changing an API model
SIFT_LIVE_URL=<reel url> uv run pytest -m live    # one real end-to-end run (spends API credits)
```

The web app lives in `web/`. `sift run` serves the last build in `web/dist`, so rebuild after changing it (`check.sh` does), or use the dev server while you work on it. It talks to the server only through `web/src/api/`.

Read `DESIGN.md` for the architecture and `DECISIONS.md` for the choices made while building the prototype.

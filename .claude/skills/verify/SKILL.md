---
name: verify
description: Verify a change end to end in the running Sift app -- the React web app with the agent-browser CLI, the JSON API, the CLI commands, and the rows they write in SQLite. Use after any change a user can reach, and when asked to test, check, debug, click through, or screenshot the app. Use agent-browser for pages, not the Claude in Chrome tools.
allowed-tools: Bash(agent-browser:*), Bash(curl:*), Bash(uv run:*), Bash(bun run:*), Bash(bun install:*), Bash(sqlite3:*), Bash(lsof:*)
---

Verify a change against the code in this directory, through every layer it touches.
Call `agent-browser` directly, never through `npx`.

1. **Pick the surface.** Web pages: agent-browser. `/api/` routes: `curl`. The pipeline
   (fetch, transcribe, frames, extract, score): `uv run sift process <url>`. Digest:
   `uv run sift digest`. Setup: `uv run sift doctor`. The Telegram bot cannot be driven from
   here: cover its handlers with tests, and tell the user what to send and the reply to expect.
2. **Make sure the app runs this code.** Two things can be stale: the Python process and the
   built web app.
   - The web app: `sift run` serves `web/dist`, which `bun run --cwd web build` writes
     (`.claude/scripts/check.sh` runs it last). Rebuild after any change under `web/`; a reload
     then picks it up without restarting Python. A 503 page saying the UI is not built means
     `web/dist` is missing.
   - The server: `curl -sf http://127.0.0.1:8000/health` (`WEB_HOST`/`WEB_PORT` change it; ask
     rather than read `.env`). Nothing listening (`lsof -iTCP:8000 -sTCP:LISTEN`): start
     `uv run sift run` in the background, logging to the scratchpad. Never start a second
     instance: one process runs the bot, worker and scheduler. A running process serves the
     Python code it started with; restart it if this session started it, and ask first if the
     user did.
   - Check against :8000, the app the user runs. `bun run --cwd web dev` (Vite on :5173, `/api`
     proxied to :8000) is for iterating on the UI, not for verifying it.
3. **Pages:** load the version-matched guide once per session, `agent-browser skills get core`,
   and use your own named session (`AGENT_BROWSER_SESSION`), as it says. Clear the buffers (`console --clear`, `errors --clear`, `network requests --clear`) so what
   follows belongs to this check. `open <url>`, `snapshot -i`, act on `@e` refs. The app
   updates the page without reloading it, so re-snapshot after every click, navigation or
   mutation. Check the thing that changed, plus one neighbouring flow it could break. Check
   the page at phone width (`set viewport 390 844`: shelves become a bottom tab bar), in dark
   mode (`set media dark`), and once with `set media reduced-motion`.
   - Drag and drop: drag a Kept row onto Archived in the sidebar (`agent-browser drag @row
     @shelf`), then confirm the "Archived: <title>" toast and its Undo, the shelf counts, and
     the row in SQLite. The keyboard path is the same move: focus the row, Space to pick it up,
     arrow keys to the shelf, Space to drop. Every drop has a button on the item page.
   - Adding links: the Inbox box, the sidebar's "Add link", and Cmd+V outside a text field. To
     paste without a clipboard, dispatch the event: `eval "const d=new DataTransfer();
     d.setData('text/plain','<url>'); document.body.dispatchEvent(new ClipboardEvent('paste',
     {clipboardData:d,bubbles:true}))"`. A pasted link spends live services (step 5).
   - Real iOS Safari: the user tests only on an iPhone, and agent-browser is Chromium. For any
     layout change, also render the touched pages in the iOS Simulator's Mobile Safari:
     `xcrun simctl boot "iPhone 16 Pro"` (ignore "already Booted"), `xcrun simctl openurl
     booted http://127.0.0.1:8000/<path>`, wait a few seconds, `xcrun simctl io booted
     screenshot <file>.png`. This shows WebKit rendering and safe areas, not taps:
     agent-browser's `-p ios` needs Appium, which is not installed.
4. **Check every layer, not just the pixels.**
   - `errors` and `console`: any uncaught exception or React error is a finding, even when the
     page looks right. A route that failed shows its error panel instead of the page.
   - `network requests --type fetch`: every API call is a fetch to `/api/...`. Read the status
     of each call the change makes; `network request <id>` shows the bodies. A failed write
     shows a toast and leaves the page as it was.
   - Live updates: while an item moves, `/api/status` repeats about every 1.5 s, and the list
     refetches each time `pulse.revision` changes. Once nothing moves, it slows to every 15 s
     and nothing else polls. A list that keeps refetching while idle is a finding.
   - Writes: reload the page, or read the row with `sqlite3 -readonly <db under data/>`, to
     confirm it persisted.
   - Server: the log under `data/logs/` for the request's traceback.
5. **Live services cost something.** `sift process` fetches from Instagram or Threads with the
   secondary account and spends Anthropic tokens. Use one URL per check, one the user supplied
   or one already in the database; never loop over many. When the change sits behind a fetcher
   or LLM interface, the fake-backed tests are the check, and the report says the live path was
   not run.
6. **Report evidence, not impressions:** what you ran or clicked, what it showed, the status of
   the calls behind it, every signal that was not clean, and a `screenshot` path for anything
   visual. Save screenshots and logs to the scratchpad, not the project.
7. **Clean up:** `agent-browser close`, and stop the app if this session started it.

Keep it proportionate: one happy path and the edge case the change is about. Automated
coverage belongs in tests, not here.

# Sift design

The architecture behind the V1 prototype. `SPEC.md` is the product contract. This file covers the shape of the code and why it has that shape.

## Problem

The web app, the worker and the digest scheduler share one process, one asyncio loop and one SQLite file. Four constraints shaped the design:

- **Blocking libraries.** yt-dlp, mlx-whisper, ffmpeg and sync SQLAlchemy all block. One blocking call on the loop freezes the web app.
- **Concurrent writers.** The worker advances items while the user keeps, archives and marks items done. SQLite allows one writer at a time.
- **No API key at first.** Fetching and transcription must work without one, and LLM work must wait rather than fail.
- **Spec gaps.** Scoring needs "the 10 most recent overrides", which needs a timestamp. The digest rule "not in more than 3 digests unless I interact" needs appearance counts and an interaction time.

## Usage

```python
# every channel enters the same way: the web app, /api/items, `sift process`, later Telegram
results = intake.submit(text, Origin(Channel.web), now)

# every user action goes through one function and one transition table
detail = store.apply_action(item_id, UserAction.keep, now)

# the worker's whole async surface
claimed, outcome = await worker.step()  # claim one item, run it on the pipeline thread
await notifier.item_finished(outcome)  # LogNotifier today, Telegram later

# digest: the scheduler, the web button, the API and the CLI all call this
view = await digest.deliver_digest(now, llm, notifier)
```

## Shape

**The items row is the job.** Each stage writes a checkpoint on the row: fetch, media, extract, score. Each checkpoint is a group of columns plus a `*_at` stamp. The next stage is worked out from the stamps (`lifecycle.next_stage`) and never stored. A retry, a crash or a missing API key therefore resumes where it stopped, and never downloads the post again.

**One writer per table.**
- `sift.items.store` is the only module that writes `items`.
- `sift.goals` writes `goals` and `profile`.
- `sift.digest` writes `digests` and `digest_entries`.
- `sift.inbox.imports` writes `imports` and `import_links`.
- `sift.organize.store` writes `topics`, `outlines`, `outline_labels` and `topic_merge_suggestions`.
- Two exceptions sit in `sift.items.store`, because each must share the item's transaction: `rekey` repoints `import_links`, and `delete_archived` deletes or detaches every row that names the post.

Worker writes are compare-and-set on a claim token. User actions are checked against `lifecycle.ALLOWED_FROM`. The UI draws its buttons from the same table. Queued and running items accept no user action, so the worker and the user never write the same row.

**One pipeline thread.** `pipeline.run` is plain sync code. The worker runs it on a single-thread executor, so blocking calls cannot reach the event loop. Only one item is in flight at a time, and mlx-whisper stays on one OS thread. The loop only claims items, waits and notifies.

**Waiting instead of failing.** `claim_next` skips an item whose next stage cannot run yet:
- a fetch from a paced source
- extract or score while no LLM is configured
- score while no goal is active

These items stay `queued`, and the Inbox labels them "Waiting for LLM" or "Waiting for goals".

**Attempts are counted at claim.** A post that crashes the process uses up an attempt. At startup, `reset_stuck` fails the item after 4 attempts instead of looping forever. A crash can't run backoff, so there is none on that path: the cap alone stops the loop.

**Startup safety.** One process per `DATA_DIR` holds the worker lock (`flock` on `data/worker.lock`). Only the lock holder migrates the database, resets stuck items and runs the worker.

**Typed LLM boundary.** `LLM` has one method per call (extract, score, digest, outline, brief, topic plan, setup draft). They return Pydantic outputs through `client.messages.parse`.
- The card is a union with one variant per item type, so the type and its details cannot disagree.
- On the wire the union is plain, because a pydantic discriminator emits `oneOf`, which structured outputs reject. Stored rows parse through a discriminated adapter.
- The threshold decides keep or archive, and the model's own vote is stored next to it.

**Digest rules are code.** `select_items`, `plan` and `layout` are pure functions:
- An item is eligible when it is kept and has been shown fewer than 3 times since your last action on it. Only picks and new items count as shown.
- New items all appear.
- Carryovers (eligible items already shown) appear as top picks, or wait on the bench for a refill.

The LLM picks the top items and writes the lines. Code checks the item ids and stores the digest as a queue (see "Setup, prompt boundary and digest queue").

## Web UI

The web app is a React 19 SPA in `web/` (Vite, TypeScript, TanStack Router and Query, Tailwind v4, dnd-kit, Motion), built with bun. FastAPI serves the build from `web/dist`, so `sift run` stays one process and one URL. The visual direction ("brass and steel": the keep threshold drawn as one brass line through every scored list) and the arena record behind this design live outside the repo; the code below is what came of it.

**The server's view models are the client's types.** `bun run --cwd web api` runs `sift/web/openapi.py` (the router alone, so codegen needs no `.env`, database or runtime) through openapi-typescript into `web/src/api/schema.gen.ts`. `check.sh` fails when that file and the API disagree. There is no TypeScript copy of any model. Server enums become words and icons in `web/src/lib/vocabulary.ts`, one exhaustive `Record` per enum, and `CardBody` switches exhaustively on the card union, so a value added in Python fails `tsc` until the UI handles it. View membership, allowed actions, state labels and threshold decisions stay in Python.

**`web/src/api` is the only path to the server.** It exports query factories (`api.items(filter)`, `api.item(id)` and the rest), one hook per write, `usePulse` and `useStatus`. Biome rejects imports of the client, the generated schema, `openapi-fetch` and the `fetch` global anywhere else.

**Writes refetch everything on screen.** The query client's `MutationCache` invalidates every query when any mutation settles (success or error, so a 409 still redraws), and toasts the error unless the mutation sets `meta.quietErrors` because its form shows the error inline. `useItemAction` also writes the returned `ItemDetail` into the item's cache. No mutation invalidates anything by hand.

**One heartbeat drives live updates.** `GET /api/status` returns the frame (shelf counts, notice, threshold, time zone, digest schedule) plus `pulse` and `in_motion`. `pulse.revision` hashes the status counts, the moving items' labels, the newest user action and the newest digest, so it moves for worker progress, actions from any channel and scheduled digests. The SPA polls it every 1.5 s while `pulse.busy` and every 15 s otherwise; `busy` ignores items waiting on a retry backoff or an LLM. When the revision moves, every other query refetches. An id that leaves `in_motion` has settled, and the root layout toasts its outcome ("Kept: Lucali, 86" with Open; "Archived: <title>" with Keep anyway).

**Serving.** `sift/web/spa.py` registers one catch-all after every other route and decides per request: `/api/...` gets a JSON 404, a missing build gets a 503 page with the build command (the API keeps working), files under `assets/` are cached forever, and anything else gets `index.html` with `no-cache`. A build made while `sift run` is up is served on the next reload. `sift doctor` reports a missing or stale build, and `sift run` prints the build command when it is missing.

**Writes from other sites are refused.** `write_allowed` checks `Sec-Fetch-Site` first and falls back to comparing Origin with Host when a client sends no Fetch Metadata (curl, the CLI). The refusal is a JSON 403. Vite's dev proxy (`bun run --cwd web dev`, `/api` to :8000) works with or without `changeOrigin`, because the browser's `Sec-Fetch-Site` passes through it.

### Web UI implementation reconciliation

Deviations from the arena's synthesis and its base design, each made while building:

- **No shadcn CLI.** shadcn 4.21.5 rewrote the `@/lib/utils` alias into an npm package named `cn` and installed it. `web/src/components/ui/` holds small hand-written primitives on `radix-ui` and `class-variance-authority` instead (button, fields, popover, sheet, tag, toaster), so `components.json` and the `ui:add` script were dropped.
- **Native `<select>` and `<details>`** replace shadcn's Select and Collapsible. A native select opens the phone's own picker, and the library filters stay visible on phones (they wrap under the search box) instead of folding into a sheet.
- **Item actions report through toasts everywhere**, success ("Archived") and failure (the server's 409 sentence), rather than an inline message under the item page's buttons. It is one rule for buttons, drops and keyboard shortcuts.
- **Shelf counts match their lists.** `nav.kept` counts kept and done items, which is what the Kept list shows; the old nav counted kept only.
- **The verdict reads the stored `threshold_decision`**, never `score >= threshold`, so an item scored before a threshold change keeps the call it got.
- **Only Kept and Archived rows are draggable.** No Inbox item allows keep or archive, and keeping the Inbox row a plain link lets its Retry button sit outside the anchor. Draggable rows carry `role="link"` because dnd-kit gives a draggable without a role the button role, and only Space picks a row up, so Enter still opens it. Pointer activation uses dnd-kit's defaults (200 ms or 5 px), and only the mouse starts a drag; touch and pen swipe instead. `isMousePointer` in `lib/swipe.ts` makes that call for both.
- **The phone Inbox shows the stage track without the state label**, and Retry takes the track's place on a failed row; at 390 px both did not fit beside a title.
- **A theme control** (System, Light, Dark) sits in the settings menu behind the gear at the foot of the sidebar, beside the link to the Roadmap page, and in the phone's More sheet, and sets `[data-theme]` on `<html>`; the choice is kept in `localStorage`. Both pickers read one store in `lib/theme.ts`, which also points both `theme-color` metas at a manual theme's color and gives them back their media queries under System. It reads those colors from the computed `--pan`, so `styles.css` is their one source (index.html's metas only cover first paint), and a `storage` listener keeps other tabs and the installed app in step. A known limit: the iOS standalone status bar and launch splash follow the system theme, not this override.
- **Phones get a dock, not the sidebar.** Five tabs: Inbox, Digest, a filled Add, Kept, and More (Topics, Archived, Goals, Import, Save from iPhone and Roadmap, from `lib/nav.ts`). Add opens a bottom sheet with "Paste link from clipboard" where the Clipboard API exists (secure contexts only) and a focused field otherwise. Paste reads the clipboard without focusing the field, so a good read submits and closes with no keyboard; a failed read says "Tap the field and paste" and focuses the field. A sheet opened through `useAddLink` (the Inbox empty state) returns focus to its opener; the sheet rides above the keyboard through `visualViewport`. A page can put its own bar in the dock through `DockPortal`; the item page puts its actions there. The dock's measured height is `--dock-h`, which the main padding and the toasts read.
- **Touch swipes instead of drags.** On Kept, Archived and failed Inbox rows, a swipe right runs Keep anyway, Mark done or Not done, and a swipe left runs Archive, whichever `item.actions` allows (`lib/swipe.ts`), with the same Undo toast as a drop. Undo runs whichever allowed action returns the item to the status it had. Nothing returns an item to failed, so a failed row's toast offers Reprocess instead. A committed swipe parks the row off-screen until its action settles: a failure or an unchanged status brings it back, and a new status redraws the row or drops it from a list that refetches a tick later. The click that ends a swipe is swallowed by a flag set when the gesture locks to x and cleared by the next pointerdown of any pointer. A floating Add button was tried and dropped: it covered row buttons at 375 px and the item page's actions.
- **The iOS status bar style is `default`, not `black-translucent`.** `black-translucent` always draws white glyphs, which vanished over the light theme's top strip. With `default`, iOS draws the status bar itself, colored by `theme-color`, and the page starts below it, so the top strip was deleted. The cost is that nothing draws under the status bar, which the design never used. On wide landscape screens the sidebar and main column add the left and right safe-area insets, so nothing sits under the notch.
- **The bundle is 872 kB (278 kB gzipped)**, not the sketch's 440 kB, which was measured with stub components. It stays one chunk on purpose; `vite.config.ts` raises the warning limit rather than splitting a localhost app.
- **The Jinja pages were deleted with the backend contract**, not after the pages were built: the typed status and submissions removed the helpers `pages.py` used, and keeping it compiling would have meant compatibility code.
- **The drag preview is a chip**, not the row. A `DragOverlay` in `shelf.tsx` shows the thumbnail and title, 40 px tall, next to the grab point. Topics in the sidebar take drops as well as the shelves.
- **On a phone, a post moves to a topic through a Move to sheet** on the item page, which lists Sift's pick and every topic. Wider screens keep the native select.
- **The Roadmap page is static.** Its stages and entries live in `web/src/lib/roadmap.ts`, which is the one place to update when a step ships. The brass Today line sits above the first stage not built, echoing the keep line in the lists.

## Import

Importing the posts saved before Sift existed, from Meta's "Download your information" zip. An arena produced two designs; candidate 1 is the base, with candidate 2's pacing gate, option cards and 422 message grafted on. Milestone M1 is the import; M2 is the organization below.

```python
scan = export.scan(zip_path)  # pure; NotAnExport -> 422
view = imports.stage(scan, filename, now, pace, llm_ready=...)  # preview; nothing reaches the pipeline
view = imports.apply(view.id, ImportAction.start, now, pace, llm_ready=..., limit=100)
imports.release_next(now, pace, llm_ready=...)  # worker loop, before each claim
```

**A staging table, then the paste path.** `imports` holds one uploaded export and `import_links` one row per distinct post in it (`found`, `waiting`, `released`, `duplicate`, `skipped`). `sift.inbox.imports` is their only writer. Items are still created only by `store.enqueue` with `Origin(Channel.export)`, so dedup and the items row are exactly a pasted link's. The import's phase (preview, running, paused, finished, cancelled) is derived from its stamps and its waiting count, like `next_stage`.

**Reading the export.** `export.scan` opens only members whose path has a whole token `saved` and no `messages`, `inbox` or `threads` token. Imports are Instagram only: Threads has no export of saved posts alone, so a Threads link found in a saved file is dropped. Every string goes through `urls.find_urls` and `urls.parse_url`; an epoch `*timestamp*` on the nearest enclosing object becomes `saved_at`. `parse_url` tags each unsupported link with a kind: profile URLs (`meta_page`) are dropped silently, since newer exports list each post's owner; other Instagram or Threads URLs (`meta_other`) count as unreadable. Saved posts are read first and collections last. A file over 64 MB is listed as too large; files left once the 256 MB total runs out are listed separately as not read.

**The drip.** `release_next` runs on the pipeline thread before each claim and releases at most one link. The pure `gate()` decides from a `DripState`, in order: paused; auto-pause when the 5 newest releases since the last start or resume all failed their first fetch; `in_flight` while an imported post is unsettled and not in retry backoff; `daily_cap` while `IMPORT_DAILY_CAP` links were released in the last 24 hours; `gap` until the stored next release time (jittered per link). The hold and its time go to the UI. Enqueueing the item and marking the link share one transaction, so a crash leaves the link waiting; an `Existing` result marks the link duplicate.

**Quiet.** `Channel.export` is in `QUIET_CHANNELS`: the worker skips the notifier, and `ItemMotion.announce` is false, so the SPA does not toast each imported post. The status revision includes the newest `imports.updated_at`, so every release, pause or cancel refetches the screen.

**Web.** `POST /api/imports` takes the zip as the raw `application/zip` body, streams it to `DATA_DIR/imports/` under `IMPORT_MAX_BYTES` (413), scans it on a thread, stages it, and deletes the file in a `finally`. `gen-api.ts` maps `format: binary` to `Blob`, so `useUploadImport` sends a `File`. `/import` shows the steps, a drop zone, and each import: a ledger and priced option cards in preview, then a graphite progress line, outcomes, the hold, Pause, Resume and Cancel. The Inbox shows one banner line while an import runs or is paused, and imported rows carry an "Imported" chip.

### Import implementation reconciliation

Deviations from the arena's synthesis and candidate 1's design, each made while building:

- **The hold is `in_flight`, not "one downloading".** Any unsettled imported post outside retry backoff holds the drip, not only an unfetched one. The drip then also waits while a post waits for an LLM or a goal, so the Inbox never holds more than one imported post. With one pipeline thread and a 3-minute gap this costs no time.
- **Auto-pause counts failed first fetches that point at the account or the tools** since the last start or resume: a fetch in retry backoff, or one that failed as `download_failed`. Login walls, rate limits, geo blocks and age gates classify that way. A dead post (`post_unavailable`) neither counts nor resets the count, because an expired session can also make live posts read as private. Resume restarts the count, which needed a `resumed_at` column.
- **`pause_reason` is an enum** (`user`, `download_failures`); the SPA owns the wording, as with `Notice`.
- **The gap is global.** The gate reads the latest next release time across imports, and the drip serves the oldest running import, so two running imports do not double the pace.
- **Dead posts have their own kind, `post_unavailable`**, with its own hint, so auto-pause can skip them. Only an error from the post page or extraction can mark a post dead: the Instagram fetcher extracts with `download=False` first, and an error while downloading the media (a 404 on a CDN URL or fragment) stays a retryable `download_failed`. Threads' oEmbed 400 and 404 are `post_unavailable` too, so both sources classify alike.
- **Keep and Mark done need a scored item.** Archive from failed was the parent decision; without this rule, Keep anyway on an archived dead link would put an empty card in Kept and the digest. `lifecycle.allowed_actions` takes `scored`, and such an item offers only Reprocess.
- **The server prices the "Newest N" field too**, through `GET /api/imports/{id}/estimate?limit=N`, debounced 250 ms in `useImportEstimate`, so the browser keeps no copy of `drip_duration`.
- **A failed Inbox row allows Archive but stays a plain link, not draggable**, so the Web UI rule above (only Kept and Archived rows drag) holds; a dead link is archived from its page.
- **Duplicates at preview also cover links waiting in another import** (candidate 2's "held by another open batch").
- **`ImportView.current`** names the imported post in flight and its state label, so a hold that lasts (Waiting for LLM) explains itself.
- **The fake backend prices at $0**, through a `fake` row in the price table, rather than showing tokens only.
- **`IMPORT_GAP_SECONDS` has a floor of 1 second**, not 20, so the end-to-end check can run in a minute; the README says to keep it at or above `FETCH_DELAY_SECONDS`.
- **Import sits behind the phone dock's More sheet**, with Digests and Goals; M2's Topics goes there too.
- **No `meta_export_shape.json` fixture yet.** Graft 9 records a real export's key shapes once one is available; none is.
- **`.env.example` is unchanged.** The session that built this could not read it; the three settings are documented in the README and default sensibly.

## Organization

Topics, a one-line gist, key points and labels per post, one cited brief per topic, and posts that add nothing new folded under the post that covers them. Same arena as Import: candidate 1 is the base, with candidate 2's read-time folds, Haiku briefs, merge proposals and liveness checks grafted on. The pipeline, `extract`, `score` and their LLM contracts are untouched.

```python
did_work = organizer.step(llm, import_running=imports.running())  # worker idle time, at most one LLM call
items = queries.list_items(ItemFilter(KEPT, topic_id=7, label="date night"), llm_ready=...)
view = organize.store.list_topics()  # grouped by goal, with merge suggestions
detail = organize.store.get_topic(7)  # brief with numbered citations, sources, freshness
organize.store.move_item(item_id, topic_id=3, now)  # your move wins over Sift's pick
organize.store.merge_topics(9, into_id=3, now=now)
```

**Own tables, no column on `items`.** `sift.organize.store` is the only writer of `topics`, `outlines`, `outline_labels` and `topic_merge_suggestions`.
- An outline is fresh only while `outlines.extracted_at` equals the item's, which the join checks. A reprocess clears `extracted_at`, so the old outline drops out of every view with no write here.
- The user's topic (`topic_override_id`) sits beside Sift's pick (`topic_id`); the effective topic is `coalesce(override, pick)`. A re-outline rewrites the pick and keeps the move. The 10 newest moves go into the outline prompt, the way overrides feed scoring.
- A merged topic stays as an alias of its survivor, and a dissolved one as a tombstone, so a later proposal of either name never recreates it.

**The organizer** (`sift/organize/organizer.py`) runs on the pipeline thread when nothing can be claimed, so a pasted link waits behind one organizer call at most. Each step runs one job, in this order: a brief you asked for; the first shelves; an outline (kept posts first, then newest); merge suggestions after the topics changed; a brief that has settled. Every job derives what is missing or stale, so a crash or restart converges. A failing target (a refusal, an outage, a bug) backs off for 30 minutes alone.

| Job | Model | When | Cost on Haiku 5.5 |
|---|---|---|---|
| Outline: gist, key points, labels, topic pick | `llm.outline`, strict, `OUTLINE_MODEL` | each extracted post, including the backlog | about $0.0008 a post |
| First shelves from up to 25 posts | `llm.plan_topics`, strict, `OUTLINE_MODEL` | once, while no topic has ever existed and 6 or more posts wait | about $0.0006 once |
| Merge suggestions | `llm.plan_topics`, strict, `OUTLINE_MODEL` | after a topic is created, renamed, merged or removed | about $0.0003 a check |
| Brief, a full rewrite with the previous wording passed for stability | `llm.compose_brief`, strict, `BRIEF_MODEL` | 30 minutes after a topic's posts stop changing; a day at most while an import runs; at once when asked | about $0.002 (20 posts) to $0.004 (60) |
| Folds, label cleanup, topic goal | code | at read | 0 |

**Strict schemas within a union budget.** `OutlineDraft` has 2 unions (`topic_id`, `new_topic`), `BriefDraft` and `TopicPlanDraft` none. `tests/test_schemas.py` pins each count, so a new nullable field fails a test instead of the API. There are no length bounds in the schemas: the SDK strips them and then fails the parse client-side, so `model.normalize_outline` trims instead, and `parse_brief` drops invented point numbers and uncited points.

**Writes during an LLM call.** No write transaction spans a call.
- `record_outline` is compare-and-set on the item's `extracted_at`, and resolves the topic pick inside the write: a merged topic maps to its survivor, a dissolved one sends the post back for re-homing (`needs_topic`), and a dissolved name is never recreated.
- `record_brief` writes nothing to a merged or dissolved topic. It stores the basis it read, so if members changed during the call the brief is stale at once and rewritten after the next settle.

**Brief dirtiness is a basis hash** over the kept members' `(item_id, outlined_at)`. Keep, archive, done, a move, a merge and a reprocess all change it without touching `topics`. `brief_targets` runs the settle clock (`pending_basis`, `pending_since`, `dirty_since`) and clears the brief of a topic left with fewer than two kept posts.

**Folds are derived at read time, from point-level citations.** The brief cites `(item_id, key point index)` and stores each source's `outlined_at` and point count. On every read, `model.derive_folds` runs over the sources that are still kept, still on the topic and outlined as the brief read them. Post B folds under A when every key point of B is cited, every brief point citing B also cites A, and A outranks B (citations, points, relevance, earlier saved); a cover is then never itself covered, so lists nest one level. An uncited point keeps a post visible. Archiving the cover or moving either post unfolds at once, with no write. Every list row carries `covered_by`, so a covered post found by search still says so; the SPA nests a row only when its cover is in the list.

**Digest.** A post covered by another eligible candidate leaves the slot to its cover (`digest.select_items`).

**Status.** `pulse.revision` includes the newest outline, move, topic change, brief and suggestion. `pulse.busy` holds while a brief you asked for is unwritten, so the topic page sees it land. `nav.topics` counts topics with a kept post.

**Web.** `GET /api/items` gains `topic_id` and `label`, and search also matches the gist. List rows gain `gist`, `labels`, `topic` and `covered_by`; the item page gains `organization`. Topic routes: `GET /api/topics`, `GET`/`PATCH`/`DELETE /api/topics/{id}`, `POST /api/topics/{id}/merge`, `POST /api/topics/{id}/brief` (202), `POST /api/topics/{id}/suggestions/{into_id}/dismiss`, `PUT /api/items/{id}/topic`, `GET /api/labels`. `DELETE` returns a body, because `unwrap()` treats an empty response as an error; a bodiless write uses `ok()` instead.

### Organization implementation reconciliation

Deviations from the synthesis and candidate 1's design, each made while building:

- **Two model settings, `OUTLINE_MODEL` and `BRIEF_MODEL`**, both `claude-haiku-5-5`, rather than one `ORGANIZE_MODEL`. Seeding and merge suggestions use `OUTLINE_MODEL`.
- **Merge suggestions have their own table, `topic_merge_suggestions`.** The synthesis named three tables, but a suggestion must survive until you act on it, and a dismissed pair must never come back.
- **One LLM method, `plan_topics`, serves both the first shelves and merge suggestions** (prompt `topics_system.md`, after candidate 2's `assign_system.md`). Code still enforces smaller into larger, at most two, both live, no chains and no dismissed pair.
- **The batched cold start names the shelves but does not place posts.** Each post's outline places it, choosing among the seeded topics. This keeps one writer of a post's topic pick. It runs once per process when it names nothing, so an empty answer cannot loop.
- **The merge check's stamp is process-local**, like the backoff. A restart costs one repeat check.
- **A kept or done post left unsorted is re-outlined when the topics change after its outline** (graft 7), or when you keep it after it was outlined. Queued and archived posts are not retried for this. It costs one outline per such post per change.
- **Briefs are shorter than candidate 1's prompt asked:** 2 to 5 sections, points under 160 characters, a one-sentence overview, following the 2026-10-23 principle that reducing information fatigue is the main job.
- **The digest drops a covered post when its cover is an eligible candidate**, not any kept post. A cover already shown 3 times therefore lets the covered post appear.
- **A requested brief that fails at any step after its request is taken clears the request**, so `pulse.busy` does not hold for the 30-minute backoff. Asking again retries at once; a request made before the failure, one whose clear also failed, waits out the backoff.
- **A brief's `brief_at` is when its input was read**, not when it was saved, so a request made while it was being written is served next.
- **A brief reads the 60 most relevant kept posts, and its basis, its fresh or stale state and "covers N of M" use that same selection.** A change to a post outside it never rewrites the brief.
- **An outline stops after 3 failed attempts** until a reprocess gives the post a new `extracted_at`, or, for an unsorted kept post, until the topics change again. The count is process-local, like the backoff, so a restart allows 3 more.
- **Only kept and done posts create topics, and the 40-topic cap counts live topics.** Queued and archived posts join a live topic or stay unsorted. The live count bounds the list every outline prompt carries. An empty topic holds a slot until you merge or dissolve it, and is never dissolved automatically, because a tombstone would retire its name.
- **A move is refused (409) while the post's outline is stale** (during a reprocess), not only when it has none.
- **Renaming onto a tombstone's name takes the name over.** The tombstone's slug gets a `~<id>` suffix.
- **`GET /api/topics` returns `{groups, suggestions, options}`**: topics grouped by the goal most of their kept posts matched (goal order as on the Goals page, no goal last), the pending suggestions, and every live topic for pickers.
- **The import estimate includes the outline call** ($0.0008 at the design's token estimate, not yet measured), so a post costs about $0.0246 on the default models.
- **`sift doctor` checks every configured model**, not only `EXTRACT_MODEL`.
- **`.env.example` is unchanged**; the building session could not read it. `OUTLINE_MODEL` and `BRIEF_MODEL` are in the README.

## Setup, prompt boundary and digest queue

Three changes from one arena (2026-10-25): goals and values drafted from a few questions, one structural boundary for untrusted text, and a digest stored as data so a done pick is refilled. Candidate B is the base, with candidate A's Clip caps, old-digest parse and question set grafted on.

```python
view = goals.setup_view()  # QUESTIONS plus the answers saved by the last apply
plan = goals.draft_setup(answers, llm)  # one LLM call; writes nothing
goals.apply_setup(SetupApply(answers=..., add=..., deactivate=[2], values_text=...), now)
store.record_extraction(claim, guards.ground_links(out, inp), model, now)
view = digest.get_digest(digest_id, llm_ready=True)  # top: the first 3 queue entries still kept
```

**Setup.** `sift.goals.QUESTIONS` is the one list of 7 questions: four written (what you saved and why, what you are working toward, why you rarely go back, what counts as noise) and three choices (areas, with a write-in; who you plan with; how strict). `GET /api/setup` serves it with the answers saved by the last apply. `POST /api/setup/draft` validates the answers against the list (422), runs one `DIGEST_MODEL` call, and returns a `SetupPlan {add, deactivate, values_text}` clipped to the API's bounds. The prompt shows the current goals with their ids and aims for 2 to 6 goals in all. Each drafted goal carries `revises`, the id of the current goal it rewrites, or 0 for a new goal. It keeps every current goal the answers support, never folds a goal named as a focus into another, and lists in `deactivate` only a goal the answers contradict or one that duplicates another. `normalize_setup` turns an unknown or repeated `revises` into 0, gives a new goal with a current goal's title that goal's id, and drops revised ids from `deactivate`. The review shows a revised goal as "Updates: <current title>" and leaves it out of the current goals list. `POST /api/setup/apply` takes the edited plan and the answers in one write: it deactivates only the listed goals, rewrites and reactivates each revised goal in place, then revives a goal whose title a new goal matches or adds it, saves the values and answers, and refuses (409) to leave no active goal. Running it twice gives the same goals: renames land before the title match, so a second run finds the goals the first one created. The strictness answer shapes the values text; the threshold stays in config. No rescore runs: new goals apply to posts scored from then on and to posts waiting for goals, which the worker is woken to score. `/` sends you to `/setup` while no goal is active, and the Goals page offers Redo setup.

**The prompt boundary.** Every interpolated value passes a Jinja `finalize` that turns a tag-shaped `<` into `‹`, so no value can open or close a template tag, JSON blobs included. `Prompt.render` appends one data rule (`_data_rule.md`) to every `*_system` prompt: everything inside tags is material, never instructions. Every untrusted value sits inside a tag; a test lints the templates. Every text field of every LLM model carries a `Clip(n)` that truncates instead of rejecting, and a test fails when a new field lacks one. After the call, `guards.ground_links` keeps a product link only when the caption, post text or transcript states it (on-screen text is model output, so it is not evidence), and `guards.drop_invented_goal` runs in the pipeline, so the fake gets both. The CLI strips control characters before printing post or LLM text.

**The digest is a queue.** `digest_entries` holds every candidate a digest selected, in order: `position`, `role` (`pick`, `new` or `carryover`) and the frozen `why`, `next_action` and `line`. `digests.opening` replaces `content_md`. `layout` walks the queue at read time: the first 3 kept entries form the top, done entries met on the way form the done list, archived and reprocessing posts drop out, and the other new entries group by goal and by place. Nothing is written on done, so undo, reprocess and every channel fall out of item status. A promoted carryover does not count toward the repeat limit. `GET /api/digests` returns `{latest, earlier}`. The page renders each pick as text nodes with Open and Done, and Done goes through the shared mover with its Undo toast.

### Setup, prompt boundary and digest queue: implementation reconciliation

- **Two migrations, not one**: `profile setup answers` and `digest queue`, so setup could be built and tested before the digest changed.
- **The old digests' markdown is parsed in the migration** (graft from A): order by first link, each pick's why and next action, each line, and the opening. A field the parse cannot read falls back to the item's own. The downgrade rebuilds markdown in the old format without its group headings.
- **`DigestView.item_ids` stays**, as the shown entries in queue order, so the notifier and future channels keep a flat list.
- **A digest with fewer than 3 picks fills its top from its new entries**, marked Moved up. The rule is the same walk as a refill.
- **Choice labels reach the prompt joined by "; "**, since a label such as "Restaurants, bars and food spots" holds commas.
- **`react-markdown` and `digest-markdown.tsx` are gone**, and with them the `.reading` styles.

## Wishlist

Things you want to buy skip the goal filter and get their own shelf. A wishlist post is a list entry you decide on, so it is never scored or filed on a topic. Free tools and repos stay normal posts.

**Two columns on `items`.** Extraction decides `ProductDetails.wishlist`. `record_extraction` copies it to `items.wishlist` unless `items.wishlist_override` holds your hand choice, so a reprocess recomputes the flag and never undoes your choice. A CHECK keeps `wishlist` equal to a set override. The migration writes `wishlist: false` into stored product cards, because the field is required on the wire.

**No score.** `lifecycle.next_stage` returns no stage once a post on the wishlist (the flag or your add) is extracted, so the Inbox, `/api/status` and the claim never read it as waiting to be scored. The pipeline settles it with `store.record_wishlist`: kept, no score, and the fetch notes as the status reason, or "On your wishlist" when there are none. Reprocess follows the same rule. A post saved before this rule and still queued for scoring settles the same way on its next claim, goals or not.

**A settled post stays settled.** `items.processed_at` marks a post the pipeline settled, scored or not, and `next_stage` returns no stage while it is set. Only Reprocess and Retry clear it, so a wishlist change never sends a post back through the pipeline and never notifies Telegram again. The `settled_marker` migration clears the mark on posts that were reprocessed and never settled again, and sets it on settled posts that lacked it.

**The rule lives in `lifecycle.disposition`.** Most important first: your add to the wishlist keeps the post, then your Keep or Archive decides, then the extracted wishlist flag keeps it, then the threshold. `store.set_wishlist` (`PUT /api/items/{id}/wishlist`) takes an extracted kept or archived post and `on` of true (add), false (remove) or null (clear your choice, back to the extracted flag), and changes only the flag and the status that follows from it. It never touches your Keep or Archive, so removing a scored post falls back to it. A post with no score has no threshold to fall back to: one the pipeline settled counts as kept, so removing it leaves it kept as a normal post with no score (the organizer files it, and Keep, Done and Archive work on it), and an archived one stays archived; one you archived after it failed, and never settled, goes back to archived. Undo on the item page sends the `wishlist_override` the post had before, so undoing an add does not pin a removal. Archiving a post you added clears the add, so the archive wins and it leaves the wishlist; the list's Undo of that archive adds it back instead of sending Keep.

**Shelves are predicates.** `queries.Shelf` and `on_shelf` define Inbox, Kept, Wishlist and Archived once. Lists (`?view=`) and the nav counts both use them, so they agree. Kept is done posts plus kept posts off the wishlist. Wishlist is kept posts on it, by `lifecycle.WISHLIST_SHELF`, which `ItemSummary.wishlist` uses too, so an archived post the extraction flagged reads as off the wishlist. Archived and done wishlist posts stay where those statuses always live.

**Topics.** `organize.store.filed_outline` leaves out every row with `items.wishlist` set, so topic pages, counts, the sidebar, briefs, topic digests and the organizer skip wishlist posts. An older post that already has an outline keeps it; it only stops counting. Once off the wishlist, a post with no outline is an organizer target like any other kept post.

**Digest.** `digest_candidates` and the topic tabs leave wishlist posts out, so the LLM never sees them. After the LLM call, `queries.wishlist_rotation` picks up to 2 kept wishlist posts: those never in a digest come first, then the ones shown longest ago, with ties going to the oldest save. They are stored as `wishlist` entries, which is how they rotate. `layout` lists them under "On your wishlist" while they are kept and on the wishlist. A digest still needs a goal post to exist; wishlist posts alone do not make one. A kept post with no score, taken off the wishlist, is a digest candidate that `digest.by_score` ranks after every scored one.

**Web.** A Wishlist shelf at `/wishlist` sits beside Kept in the sidebar and in the phone's More sheet. Its rows show the thumbnail, product name, price and a Shop link (http and https only), and no score. `ItemSummary.wishlist_post` is the flag itself (extracted or your add) in any status, beside `wishlist`, which means the shelf. `actionWords` labels Done as Bought ("Marked bought") and Not done as Not bought when it is set. The item page offers Add to wishlist or Remove from wishlist when `can_wishlist` is true. The page layout follows `wishlist_post`, so a wishlist post keeps its short page while it is reprocessed (with the stage track and a working note in place of the shop button), archived (with Keep anyway, Bought and Add to wishlist) or bought: the first image or thumbnail, the name, what it is, the price, a "Where to get it" button (or a plain note and the original post when there is no link), the card details of a post that is not a product (a place or recipe added by hand), and Bought, Remove from wishlist, Archive or Not bought, with Reprocess as a secondary control. It shows no score, verdict, goal, next action, topic or source texts. On the normal post page, a settled post with no score shows neither the score rail nor the stage track, only its card.

## Deleting archived posts

**Only an archived post can be deleted, and the delete is complete.** `DELETE /api/items/{id}` (204, 404, or 409 for any other status) runs `store.delete_archived`, which checks `lifecycle.can_delete` in the same write, so a post Reprocess just requeued is refused. That write deletes the post's outline and labels and its digest entries, since each keys on the post, detaches its import links, then deletes the row. A detached link keeps its state and `released_at` and loses `item_id` (migration `6cf92d9cd6bf` relaxed the check to `ck_released_has_time`), because the import's daily cap counts released links by `released_at`; deleting them would let a running import fetch more than the cap within a day. The import's released count stays; its kept, archived and failed counts join live posts, so the deleted post leaves them, and the failure streak skips it the way it skips a dead post. A past digest renders without the entry, as it already skips archived posts; its shown count drops by one. A brief that cited the post keeps the citation, and the brief view already skips sources it cannot find. After the commit, `services.delete_item` removes the pipeline's `workdir` and each uploaded image no other post names, since a single image and a set can share one upload. That check is one bounded `LIKE` per name, safe because upload names are fixed-length hashes. A crash between the two leaves files, never a dangling row. Dedup finds nothing, so the same link or image comes back as a new post.

**Ids are never reused.** `items` is `AUTOINCREMENT` (migration `7e2b0c4d9a13`). Without it SQLite gives a deleted newest id to the next post, which would show the old post's day-cached thumbnail and its citations in briefs.

**Topics.** A topic's archived count drops with the outline. A topic whose only posts were archived was hidden on the Topics page; once they are all deleted it has no posts and shows there as an empty topic, the way a new topic does, and it never shows in the sidebar. `topics` does not record whether the organizer or you made a topic, so the delete cannot tell which empty topics to remove and leaves them all.

**Web.** List rows and the item page carry `can_delete` from the server, so the SPA holds no copy of the rule. The item page, in both layouts, puts a quiet red Delete under its other controls. On the Archived shelf the free left swipe deletes, in the alarm color, where other shelves archive. On a pointer that can hover, a trash button left of the score rail appears on hover or keyboard focus. Every path confirms in a bottom sheet (`ConfirmDelete`, mounted only on a deletable row) and toasts "Deleted: <title>". A cancelled swipe slides back. The item page then returns to Archived. A failure toasts the server's sentence and leaves the screen as it was. A successful delete drops the post's `['item', id]` query before the refetch on settle, so nothing asks for the deleted post and a later visit loads it fresh and shows not found. Page shortcuts (K, A, D, and `/`) stay off while any dialog or sheet is open (`ignoresShortcut`).

## Synthesis decision

Two candidate designs were produced in parallel (Opus at high and at xhigh effort), and a third Opus run judged them.

- **Candidate 1 became the base:** the status column, the items row as the job, one pipeline thread and one store. It prevents lost updates by construction with the fewest moving parts.
- **Candidate 2** split state across 10 tables: per-stage artifact tables, a status computed by joins, and five worker lanes. It modeled correctness well but cost too much to build and maintain for a single-user tool. The judge agreed on the base.

Grafted from candidate 2:
1. Attempts are counted at claim, which protects against crash loops.
2. Items wait instead of failing when there is no LLM or no goal. This replaced candidate 1's "park as failed, resume at boot" path and removed code.
3. `LLM_BACKEND=fake` lets the app be clicked through without a key.
4. The wire schema uses a plain union, after candidate 2 checked that discriminators emit `oneOf`.
5. `normalize_cron`: APScheduler counts weekdays from Monday, so numeric days are rewritten to names.

Rejected:
- Candidate 2's lanes, derived status and artifact tables.
- Candidate 1's FTS5 search: plain LIKE search across title, summary, transcript, caption, post text and on-screen text is enough at personal scale.
- Candidate 1's module-global queue listener: the worker polls every 1.5 s, and the web app wakes it directly.

## Tradeoffs accepted

- We accept serial processing (one item at a time) in exchange for no locking and a structural guarantee that blocking work stays off the loop.
- We accept a wide `items` row in exchange for single-table lists and search. CHECK constraints keep checkpoints whole.
- We accept that a running stage cannot be cancelled. On shutdown, the next startup requeues it.
- We accept two LLM calls per item (extract with images, score with text only) so that re-scoring never re-sends frames.
- We accept that the user's override survives a reprocess, so an explicit choice is never silently undone.
- **A post kept anyway takes a reason**: the goal it serves, or none of them, plus an optional note (`keep_goal_id`, `keep_note`, `keep_reason_at` on `items`). The item page asks under the verdict, and every Keep anyway toast links there with Say why. The reason rides along in two places. Scoring's override examples quote it, so the next post like it scores closer to your call at no extra cost. The setup draft reads the 20 newest reasons in `<kept_anyway>`, so Redo setup widens a goal its posts keep landing outside of, or proposes a goal for posts that fit none. Goals never change on their own; the Goals page counts the reasons given since the last setup and points to Redo setup. Archiving the post drops its reason.
- We accept best-effort notifications (no outbox table) while nothing delivers them yet.

## Alternatives considered

- **Async all the way down** (`async def fetch`, aiosqlite). Every new blocking call becomes a chance to freeze the loop, and the next contributor will copy the nearest example. The single pipeline thread removes that trap.
- **Per-stage artifact tables with derived status** (candidate 2). This design is the most correct, but it needs 10 tables, a CASE over joins behind every read, and lane concurrency.
- **Event-sourced items.** Lists and claims need an indexed status anyway, which would mean two sources of truth.

## Implementation reconciliation

Deviations from the base sketch, each made while building. None changes a shared contract.

- **`Fetcher.fetch` is sync**, and URL parsing lives in pure `sources/urls.py`, as the sketch planned. This deviates from SPEC 5.
- **The spec's `digests.item_ids` JSON became the `digest_entries` table.** The API still exposes `item_ids`.
- **Frames are spread over the whole clip** (at most 8). The spec's literal "every 3 s" would miss overlays near the end of long reels.
- **A failed Threads video degrades to a text-only item with a note.** Text is the main Threads content.
- **Reprocess clears only the extract and score checkpoints**, so it re-runs the LLM on the stored transcript and frames. To re-download, use Retry on a failed item.
- **There is no `UnconfiguredLLM`.** `llm: LLM | None` on the pipeline deps, together with the claim filter, replaces it.

## Open questions

- Should opening an item's page count as "interacting" for the digest repeat rule? Today only explicit actions count.
- Should carryover top picks resurface (up to 3 times), or should each item appear in one digest only?
- Should an Instagram login wall pause all fetching with one notification, instead of failing each item?
- Before the app is exposed over Tailscale, it needs a shared-secret check. Cross-site writes are already refused (Fetch Metadata, with an Origin fallback).

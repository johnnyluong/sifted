from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import time
from pathlib import Path

import typer
import uvicorn

from sift import digest, doctor, runtime
from sift.config import get_settings
from sift.domain import Channel, ImportAction, Origin, Source
from sift.inbox import export, imports, intake
from sift.inbox.imports import ImportView
from sift.items import queries
from sift.items.views import ItemDetail

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Sift: saved posts, filtered by your goals.")


@app.command()
def run() -> None:
    """Start the web app, worker and digest scheduler in one process."""
    from sift.web import spa
    from sift.web.app import create_app

    settings = get_settings()
    if runtime.worker_running(settings):
        typer.echo(f"Sift is already running for {settings.data_dir} (lock: {settings.run_lock_path}).", err=True)
        raise typer.Exit(1)
    runtime.setup_logging(settings)
    rt = runtime.build_runtime(settings)
    if not (spa.DIST / "index.html").is_file():
        typer.echo(f"Web UI not built; the API runs, and pages show how to build it. Build: {spa.BUILD}", err=True)
    uvicorn.run(create_app(rt), host=settings.web_host, port=settings.web_port, log_config=None)


def _settled(item: ItemDetail) -> bool:
    return not item.in_motion or item.state_label == "Retrying soon"


_ESCAPES = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?|.)?")
_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def strip_terminal_controls(text: str) -> str:
    return _CONTROLS.sub("", _ESCAPES.sub("", text))


def _echo(text: str, *, err: bool = False) -> None:
    typer.echo(strip_terminal_controls(text), err=err)


def _print_item(item: ItemDetail) -> int:
    _echo(f"#{item.id} {item.display_title}")
    _echo(f"  status: {item.state_label}")
    if item.item_type:
        _echo(f"  type:   {item.item_type.value}")
    if item.relevance_score is not None:
        _echo(f"  score:  {item.relevance_score} ({item.matched_goal_title or 'no goal'}): {item.relevance_reason}")
    if item.next_action:
        _echo(f"  next:   {item.next_action}")
    if item.transcript:
        _echo(f"  transcript: {len(item.transcript)} chars")
    if item.failure_hint:
        _echo(f"  error:  {item.status_reason}\n  hint:   {item.failure_hint}")
    return {"failed": 1, "queued": 2}.get(item.status.value, 0)


@app.command()
def process(url: str, timeout: int = typer.Option(900, help="Seconds to wait for a running server.")) -> None:
    """Process one URL. Runs the pipeline here, or hands it to a running `sift run`."""
    settings = get_settings()
    runtime.setup_logging(settings, console=False)
    rt = runtime.build_runtime(settings)
    with runtime.worker_role(rt) as is_worker:
        results = intake.submit(
            url, Origin(Channel.cli), rt.clock(), llm_ready=rt.llm_ready, resolve=rt.worker.deps.fetchers.resolve
        )
        _echo(intake.ack_text(results))
        queued = [r for r in results if isinstance(r, intake.Queued | intake.Duplicate)]
        if not queued:
            raise typer.Exit(1)
        item_id = queued[0].item.id
        if is_worker:
            asyncio.run(rt.worker.run_item(item_id))
        else:
            typer.echo("A Sift server is running; waiting for it to process the link...")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                item = queries.get_item(item_id, llm_ready=rt.llm_ready)
                if item is None or _settled(item):
                    break
                time.sleep(2)
    item = queries.get_item(item_id, llm_ready=rt.llm_ready)
    if item is None:
        typer.echo(f"Item #{item_id} is gone. A share link to a post Sift already had is removed at fetch.")
        raise typer.Exit(0)
    raise typer.Exit(_print_item(item))


def _hours(seconds: int) -> str:
    hours = seconds / 3600
    return f"{hours:.1f} hours" if hours < 48 else f"{hours / 24:.1f} days"


def preview_lines(view: ImportView, limit: int | None, pace: imports.Pace) -> list[str]:
    c = view.counts
    sources = ", ".join(f"{view.by_source[s]} {s.value.title()}" for s in Source if view.by_source[s])
    plan = imports.estimate(min(limit or c.found, c.found), pace)
    cost = (
        f"About ${plan.usd:.2f} (${view.per_post.usd:.4f} a post)"
        if plan.usd is not None and view.per_post.usd is not None
        else f"About {view.per_post.tokens:,} tokens a post"
    )
    lines = [f"Read {path}" for path in view.files_read]
    lines += [f"Skipped {path} (too large)" for path in view.files_skipped_large]
    lines += [
        f"Skipped {path} (not read: over the {export.SCAN_MAX_BYTES // 2**20} MB total)"
        for path in view.files_skipped_budget
    ]
    lines += [
        f"{c.links + view.unsupported_count:>5} saved posts ({sources or 'none supported'})",
        f"{c.duplicate:>5} already in Sift",
        f"{view.unsupported_count:>5} links Sift can't read (stories and the like)",
        f"{c.found:>5} new, newest first",
        f"Importing {plan.posts}. {cost}, and {_hours(plan.seconds)} at one post every "
        f"{view.pace.gap_seconds // 60 or 1} min, at most {view.pace.daily_cap} a day.",
    ]
    return lines


@app.command(name="import")
def import_cmd(
    zip_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="The zip Meta emailed you."),
    limit: int | None = typer.Option(None, min=1, help="Import only the newest N saved posts."),
    yes: bool = typer.Option(False, "--yes", help="Start without asking after the preview."),
) -> None:
    """Preview a Meta export's saved posts, then start the import. `sift run` does the importing."""
    settings = get_settings()
    runtime.setup_logging(settings, console=False)
    rt = runtime.build_runtime(settings)
    with runtime.worker_role(rt) as is_worker:
        try:
            scan = export.scan(zip_path)
        except export.NotAnExport as e:
            _echo(str(e), err=True)
            raise typer.Exit(1) from e
        view = imports.stage(scan, zip_path.name, rt.clock(), rt.pace, llm_ready=rt.llm_ready)
        for line in preview_lines(view, limit, rt.pace):
            _echo(line)
        if ImportAction.start not in view.actions:
            typer.echo("Nothing new to import.")
            return
        if not yes and not typer.confirm("Start?", default=False):
            typer.echo(f"Left as a preview (import {view.id}); start it from the Import page.")
            return
        imports.apply(view.id, ImportAction.start, rt.clock(), rt.pace, llm_ready=rt.llm_ready, limit=limit)
    where = "Sift is running and" if not is_worker else "Start Sift (uv run sift run) and it"
    typer.echo(f"Import {view.id} started. {where} sends one post at a time; follow it on the Import page.")


@app.command(name="digest")
def digest_cmd() -> None:
    """Generate a digest now and print it."""
    settings = get_settings()
    runtime.setup_logging(settings, console=False)
    rt = runtime.build_runtime(settings)
    with runtime.worker_role(rt):
        try:
            view = asyncio.run(digest.deliver_digest(rt.clock(), rt.llm, rt.notifier))
        except digest.DigestUnavailable as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(2) from e
    if view is None:
        typer.echo("Nothing new to surface.")
        return
    _echo(digest.to_text(view))


@app.command(name="doctor")
def doctor_cmd(cookies: bool = typer.Option(True, help="Read browser cookies (may show a Keychain prompt).")) -> None:
    """Check ffmpeg, cookies, API keys, the whisper model and the database."""
    settings = get_settings()
    failed = False
    for c in doctor.run_checks(settings, cookies=cookies):
        mark = {True: "ok  ", False: "FAIL", None: "warn"}[c.ok]
        typer.echo(f"[{mark}] {c.name:<16} {c.detail}")
        failed = failed or c.ok is False
    raise typer.Exit(1 if failed else 0)


@app.command(name="update-tools")
def update_tools() -> None:
    """Upgrade yt-dlp to its latest release and print versions."""
    for cmd in (["uv", "lock", "--upgrade-package", "yt-dlp"], ["uv", "sync"]):
        typer.echo("$ " + " ".join(cmd))
        if subprocess.run(cmd).returncode != 0:
            raise typer.Exit(1)
    subprocess.run([sys.executable, "-c", "import yt_dlp.version as v; print('yt-dlp', v.__version__)"])


def main() -> None:
    app()

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sift.domain import Origin, ProcessingError, SourceRef
from sift.items import store
from sift.items.views import ItemSummary
from sift.sources import urls


@dataclass(frozen=True, slots=True)
class Queued:
    item: ItemSummary


@dataclass(frozen=True, slots=True)
class Duplicate:
    item: ItemSummary


@dataclass(frozen=True, slots=True)
class Rejected:
    url: str
    reason: str


Submission = Queued | Duplicate | Rejected


def _as_is(ref: SourceRef) -> SourceRef:
    return ref


def submit(
    text: str,
    origin: Origin,
    now: datetime,
    *,
    llm_ready: bool,
    resolve: Callable[[SourceRef], SourceRef] = _as_is,
) -> list[Submission]:
    out: list[Submission] = []
    for url in urls.find_urls(text):
        match _parse(url, resolve):
            case Rejected() as rejected:
                out.append(rejected)
            case SourceRef() as ref:
                out.append(submit_ref(ref, url, origin, now, llm_ready=llm_ready))
    return out


def submit_ref(ref: SourceRef, url: str, origin: Origin, now: datetime, *, llm_ready: bool) -> Queued | Duplicate:
    match store.enqueue(ref, url, origin, now, llm_ready=llm_ready):
        case store.Created(item=item):
            return Queued(item)
        case store.Existing(item=item):
            return Duplicate(item)


def _parse(url: str, resolve: Callable[[SourceRef], SourceRef]) -> SourceRef | Rejected:
    match urls.parse_url(url):
        case urls.Unsupported(reason=reason):
            return Rejected(url, reason)
        case SourceRef() as ref:
            return _resolve_now_or_at_fetch(ref, resolve)


def _resolve_now_or_at_fetch(ref: SourceRef, resolve: Callable[[SourceRef], SourceRef]) -> SourceRef:
    try:
        return resolve(ref)
    except ProcessingError:
        return ref


def ack_text(results: list[Submission]) -> str:
    if not results:
        return "No Instagram or Threads link found."
    parts: list[str] = []
    for r in results:
        match r:
            case Queued():
                parts.append("Got it, processing.")
            case Duplicate(item=item):
                parts.append(f"Already saved ({item.state_label.lower()}): {item.display_title}")
            case Rejected(reason=reason):
                parts.append(reason)
    return " ".join(parts)

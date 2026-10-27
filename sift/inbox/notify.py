from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from sift.items.views import ArchivedOutcome, FailedOutcome, ItemOutcome, KeptOutcome

if TYPE_CHECKING:
    from sift.digest import DigestView

log = logging.getLogger(__name__)


class Notifier(Protocol):
    async def item_finished(self, outcome: ItemOutcome) -> None: ...

    async def digest_ready(self, digest: DigestView) -> bool: ...


class LogNotifier:
    async def item_finished(self, outcome: ItemOutcome) -> None:
        match outcome:
            case KeptOutcome():
                log.info(
                    "kept #%s %r (%s, goal=%s)",
                    outcome.item_id,
                    outcome.title,
                    outcome.item_type,
                    outcome.matched_goal_title,
                )
            case ArchivedOutcome():
                log.info("archived #%s %r: %s", outcome.item_id, outcome.title, outcome.reason)
            case FailedOutcome():
                log.info("failed #%s %s: %s (%s)", outcome.item_id, outcome.failure_kind, outcome.reason, outcome.hint)

    async def digest_ready(self, digest: DigestView) -> bool:
        log.info("digest #%s ready (%d items)", digest.id, len(digest.item_ids))
        return False

from __future__ import annotations

import logging
import re

from sift.llm.schemas import ExtractInput, ExtractOutput, ProductCard, ScoreInput, ScoreOutput

log = logging.getLogger(__name__)

_SCHEME = re.compile(r"^https?://", re.I)
_HOST_AND_PATH = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?")
_NOT_MID_HOST = r"(?<![\w.-])"
_OPTIONAL_SCHEME_AND_WWW = r"(?:https?://)?(?:www\.)?"
_HOST_ENDS_HERE = r"(?![\w-])"


def ground_links(out: ExtractOutput, inp: ExtractInput) -> ExtractOutput:
    card = out.card
    if not isinstance(card, ProductCard) or card.details.link is None:
        return out
    evidence = "\n".join(t for t in (inp.caption, inp.post_text, inp.transcript) if t)
    link = stated_url(card.details.link, evidence)
    if link == card.details.link:
        return out
    if link is None:
        log.info("dropped a product link the post does not state")
    details = card.details.model_copy(update={"link": link})
    return out.model_copy(update={"card": card.model_copy(update={"details": details})})


def stated_url(link: str, evidence: str) -> str | None:
    link = link.strip()
    bare = _SCHEME.sub("", link).casefold().removeprefix("www.").rstrip("/")
    if not _HOST_AND_PATH.fullmatch(bare):
        return None
    stated = re.compile(rf"{_NOT_MID_HOST}{_OPTIONAL_SCHEME_AND_WWW}{re.escape(bare)}{_HOST_ENDS_HERE}")
    if not stated.search(evidence.casefold()):
        return None
    return link if _SCHEME.match(link) else f"https://{link}"


def drop_invented_goal(out: ScoreOutput, inp: ScoreInput) -> ScoreOutput:
    if out.matched_goal_id is not None and out.matched_goal_id not in {g.id for g in inp.goals}:
        log.info("score returned unknown goal id %s; dropped", out.matched_goal_id)
        return out.model_copy(update={"matched_goal_id": None})
    return out

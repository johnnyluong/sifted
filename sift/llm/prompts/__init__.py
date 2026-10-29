from __future__ import annotations

import re
from enum import StrEnum
from functools import cache
from importlib import resources
from typing import Any

from jinja2 import Environment, StrictUndefined

_LT_OPENING_A_TAG = re.compile(r"<(?=\s*/|[!?A-Za-z])")
INERT_LT = "‹"


def _defuse_tags(value: object) -> str:
    return _LT_OPENING_A_TAG.sub(INERT_LT, str(value))


_env = Environment(undefined=StrictUndefined, keep_trailing_newline=False, autoescape=False, finalize=_defuse_tags)


@cache
def _source(name: str) -> str:
    return (resources.files(__package__) / f"{name}.md").read_text(encoding="utf-8")


class Prompt(StrEnum):
    extract_system = "extract_system"
    extract_user = "extract_user"
    score_system = "score_system"
    score_user = "score_user"
    digest_system = "digest_system"
    digest_user = "digest_user"
    outline_system = "outline_system"
    outline_user = "outline_user"
    brief_system = "brief_system"
    brief_user = "brief_user"
    topics_system = "topics_system"
    topics_user = "topics_user"
    rebuild_system = "rebuild_system"
    rebuild_user = "rebuild_user"
    fit_system = "fit_system"
    fit_user = "fit_user"
    setup_system = "setup_system"
    setup_user = "setup_user"

    @property
    def is_system(self) -> bool:
        return self.value.endswith("_system")

    def render(self, **ctx: Any) -> str:
        text = _env.from_string(_source(self.value)).render(**ctx).strip()
        return f"{text}\n\n{DATA_RULE}" if self.is_system else text


DATA_RULE = _source("_data_rule").strip()

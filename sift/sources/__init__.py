from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from sift.domain import Source, SourceRef
from sift.sources.base import Fetcher


@dataclass(frozen=True, slots=True)
class Fetchers:
    instagram: Fetcher
    threads: Fetcher
    image: Fetcher

    def for_source(self, source: Source) -> Fetcher:
        match source:
            case Source.instagram:
                return self.instagram
            case Source.threads:
                return self.threads
            case Source.image:
                return self.image
            case _:
                assert_never(source)

    def resolve(self, ref: SourceRef) -> SourceRef:
        return self.for_source(ref.source).resolve_share(ref) if ref.is_share else ref

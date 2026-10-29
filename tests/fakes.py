from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from sift.domain import MediaKind, Notes, ProcessingError, Source, SourceRef
from sift.sources import Fetchers
from sift.sources.base import FetchResult
from sift.sources.image import ImageFetcher


class FakeFetcher:
    source: ClassVar[Source] = Source.instagram

    def __init__(
        self,
        *,
        caption: str = "Best tacos in the East Village. The al pastor at this spot is worth the line.",
        kind: MediaKind = MediaKind.video,
        errors: list[ProcessingError] | None = None,
        notes: tuple[str, ...] = (),
    ) -> None:
        self.slides: tuple[Path, ...] = ()
        self.shares: dict[str, SourceRef] = {}
        self.caption = caption
        self.kind = kind
        self.errors: list[ProcessingError] = list(errors or [])
        self.calls: list[SourceRef] = []
        self.notes = notes

    def resolve_share(self, ref: SourceRef) -> SourceRef:
        if self.errors:
            raise self.errors.pop(0)
        return self.shares[ref.canonical_id]

    def fetch(self, ref: SourceRef, workdir: Path) -> FetchResult:
        self.calls.append(ref)
        if self.errors:
            raise self.errors.pop(0)
        workdir.mkdir(parents=True, exist_ok=True)
        thumb = workdir / "thumbnail.jpg"
        thumb.write_bytes(b"\xff\xd8\xff")
        video = None
        if self.kind is MediaKind.video:
            video = workdir / "media.mp4"
            video.write_bytes(b"fake video")
        slides = tuple(workdir / "slides" / s.name for s in self.slides)
        for src, dst in zip(self.slides, slides, strict=True):
            dst.parent.mkdir(exist_ok=True)
            dst.write_bytes(src.read_bytes())
        return FetchResult(
            media_kind=self.kind,
            author_handle="tacofan",
            caption=self.caption,
            video_path=video,
            thumbnail_path=thumb,
            slide_paths=slides,
            notes=Notes(self.notes),
        )


class FakeTranscriber:
    def __init__(self, text: str = "Order the al pastor and the horchata.") -> None:
        self.text = text
        self.calls = 0

    def transcribe(self, media: Path) -> str:
        self.calls += 1
        return self.text


def fake_fetchers(uploads_dir: Path, fetcher: FakeFetcher | None = None) -> Fetchers:
    f = fetcher or FakeFetcher()
    return Fetchers(instagram=f, threads=f, image=ImageFetcher(uploads_dir))


def no_media_tools(monkeypatch_setattr: Callable[..., None]) -> None:
    import sift.media as media

    monkeypatch_setattr(media, "probe", lambda video: (6.0, True))
    monkeypatch_setattr(media, "extract_frames", lambda video, duration, out: [])


def download_error(msg: str = "HTTP Error 429: Too Many Requests") -> ProcessingError:
    from sift.domain import FailureKind

    return ProcessingError(FailureKind.download_failed, msg, retryable=True)

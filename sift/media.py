from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sift.domain import FailureKind, MediaKind, ProcessingError

log = logging.getLogger(__name__)

FRAME_EVERY_S = 3.0
MAX_FRAMES = 8
MAX_IMAGES = 12
FRAME_LONG_EDGE = 768
SLIDE_LONG_EDGE = 1024


@dataclass(frozen=True, slots=True)
class MediaResult:
    transcript: str | None
    frame_paths: list[Path]


class Transcriber(Protocol):
    def transcribe(self, media: Path) -> str: ...


class MlxWhisperTranscriber:
    def __init__(self, model_repo: str) -> None:
        self._model = model_repo

    def transcribe(self, media: Path) -> str:
        import mlx_whisper

        result = mlx_whisper.transcribe(str(media), path_or_hf_repo=self._model)
        return str(result.get("text", "")).strip()


def frame_timestamps(duration_s: float) -> list[float]:
    if duration_s <= 0:
        return [0.0]
    n = min(MAX_FRAMES, max(1, int(duration_s // FRAME_EVERY_S)))
    return [round(duration_s * (i + 0.5) / n, 2) for i in range(n)]


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as e:
        raise ProcessingError(
            FailureKind.transcription_failed, f"{args[0]} is not installed: brew install ffmpeg", retryable=False
        ) from e
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-1:] or ["no output"]
        raise ProcessingError(FailureKind.transcription_failed, f"{args[0]} failed: {tail[0]}", retryable=True)
    return proc


def probe(video: Path) -> tuple[float, bool]:
    proc = _run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(video)]
    )
    info = json.loads(proc.stdout or "{}")
    duration = float(info.get("format", {}).get("duration") or 0)
    has_audio = any(st.get("codec_type") == "audio" for st in info.get("streams", []))
    return duration, has_audio


def _fit(edge: int) -> str:
    return f"scale='if(gt(iw,ih),min(iw,{edge}),-2)':'if(gt(iw,ih),-2,min(ih,{edge}))'"


def extract_frames(video: Path, duration_s: float, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = _fit(FRAME_LONG_EDGE)
    frames: list[Path] = []
    for i, t in enumerate(frame_timestamps(duration_s)):
        path = out_dir / f"frame_{i:02d}.jpg"
        _run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                str(t),
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-vf",
                scale,
                "-q:v",
                "4",
                str(path),
            ]
        )
        if path.exists():
            frames.append(path)
    return frames


def shrink_slides(slides: list[Path], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for slide in slides:
        path = out_dir / slide.name
        try:
            _run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(slide), "-vf", _fit(SLIDE_LONG_EDGE), "-q:v", "4", str(path)]
            )
        except ProcessingError as e:
            if not e.retryable:
                raise
            log.info("skipped slide %s: %s", slide.name, e.message)
            continue
        out.append(path)
    return out


def process_media(
    kind: MediaKind,
    video: Path | None,
    thumbnail: Path | None,
    slides: list[Path],
    workdir: Path,
    transcriber: Transcriber,
) -> MediaResult:
    match kind:
        case MediaKind.video:
            assert video is not None
            duration, has_audio = probe(video)
            try:
                transcript = transcriber.transcribe(video) if has_audio else ""
            except Exception as e:
                raise ProcessingError(
                    FailureKind.transcription_failed, f"Transcription failed: {type(e).__name__}", retryable=True
                ) from e
            frames = extract_frames(video, duration, workdir / "frames")
            room = max(0, MAX_IMAGES - len(frames))
            return MediaResult(transcript, frames + shrink_slides(slides[:room], workdir / "frames"))
        case MediaKind.image:
            return MediaResult(None, shrink_slides(slides, workdir / "frames") or ([thumbnail] if thumbnail else []))
        case MediaKind.text:
            return MediaResult(None, [])

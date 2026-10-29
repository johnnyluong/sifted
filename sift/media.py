from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from sift.domain import FailureKind, MediaKind, ProcessingError

log = logging.getLogger(__name__)

FRAME_EVERY_S = 3.0
MAX_FRAMES = 8
MAX_IMAGES = 12
FRAME_LONG_EDGE = 768
SLIDE_LONG_EDGE = 1024
# Screenshots are text, so their tiles go up to the model's 1568px long-edge limit.
SCREENSHOT_LONG_EDGE = 1568
_ON_WHITE = "split[a][b];[a]drawbox=t=fill:c=white,format=rgb24[bg];[bg][b]overlay=format=auto,format=rgb24"

ImageFormat = Literal["png", "jpg", "webp", "gif", "heif"]

_HEIF_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1"})


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


def image_format(data: bytes) -> ImageFormat | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return "heif"
    return None


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


def image_size(image: Path) -> tuple[int, int]:
    proc = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(image),
        ]
    )
    [stream, *_] = json.loads(proc.stdout or "{}").get("streams") or [{}]
    width, height = stream.get("width"), stream.get("height")
    if not width or not height:
        raise ProcessingError(FailureKind.unsupported_url, f"{image.name} holds no picture.", retryable=False)
    return int(width), int(height)


def fit(edge: int) -> str:
    return f"scale='if(gt(iw,ih),min(iw,{edge}),-2)':'if(gt(iw,ih),-2,min(ih,{edge}))'"


def upright(image: Path, out: Path) -> Path:
    # ffmpeg rotates by EXIF on decode, so the tiles are measured on this copy; JPEG would turn transparency black.
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(image), "-frames:v", "1", "-filter_complex", _ON_WHITE, str(out)])
    return out


def write_jpeg(image: Path, out: Path, vf: str, quality: int = 4) -> Path:
    # Always JPEG: ffmpeg built without libwebp cannot write WebP, and a GIF sends only its first frame.
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(image), "-frames:v", "1", "-vf", vf, "-q:v", str(quality), str(out)])
    return out


def extract_frames(video: Path, duration_s: float, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = fit(FRAME_LONG_EDGE)
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


def shrink_slides(slides: list[Path], out_dir: Path, long_edge: int = SLIDE_LONG_EDGE) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for slide in slides:
        try:
            path = write_jpeg(slide, out_dir / f"{slide.stem}.jpg", fit(long_edge))
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
    slide_edge: int = SLIDE_LONG_EDGE,
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
            return MediaResult(transcript, frames + shrink_slides(slides[:room], workdir / "frames", slide_edge))
        case MediaKind.image:
            return MediaResult(
                None, shrink_slides(slides, workdir / "frames", slide_edge) or ([thumbnail] if thumbnail else [])
            )
        case MediaKind.text:
            return MediaResult(None, [])

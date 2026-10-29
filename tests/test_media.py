from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from sift.domain import FailureKind, MediaKind, ProcessingError
from sift.media import (
    MAX_FRAMES,
    MAX_IMAGES,
    SLIDE_LONG_EDGE,
    extract_frames,
    frame_timestamps,
    image_size,
    probe,
    process_media,
    shrink_slides,
)
from tests.fakes import FakeTranscriber


def test_frame_timestamps() -> None:
    assert frame_timestamps(0) == [0.0]
    assert len(frame_timestamps(9)) == 3
    long = frame_timestamps(60)
    assert len(long) == MAX_FRAMES and long[-1] > 50


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_probe_and_frames_on_a_generated_clip(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1080x1920:rate=10:duration=7",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=7",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
    )
    duration, has_audio = probe(clip)
    assert 6.5 < duration < 7.5 and has_audio
    frames = extract_frames(clip, duration, tmp_path / "frames")
    assert len(frames) == 2 and all(f.stat().st_size > 0 for f in frames)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(frames[0])],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out == "432,768"


def test_image_post_without_slides_uses_thumbnail_as_frame(tmp_path: Path) -> None:
    thumb = tmp_path / "t.jpg"
    result = process_media(MediaKind.image, None, thumb, [], tmp_path, transcriber=FakeTranscriber())
    assert result.transcript is None and result.frame_paths == [thumb]


def _image(path: Path, size: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}", "-frames:v", "1", str(path)], check=True
    )
    return path


def _size(path: Path) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_slides_are_shrunk_but_never_enlarged(tmp_path: Path) -> None:
    big = _image(tmp_path / "slides" / "slide_01.jpg", "1080x1350")
    small = _image(tmp_path / "slides" / "slide_02.jpg", "400x300")
    frames = shrink_slides([big, small], tmp_path / "frames")
    assert [f.name for f in frames] == ["slide_01.jpg", "slide_02.jpg"]
    assert _size(frames[0]) == f"820,{SLIDE_LONG_EDGE}", "even width, as -2 asks"
    assert _size(frames[1]) == "400,300"
    result = process_media(MediaKind.image, None, big, [big, small], tmp_path, transcriber=FakeTranscriber())
    assert result.frame_paths == frames


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_a_slide_ffmpeg_cannot_read_is_skipped(tmp_path: Path) -> None:
    good = _image(tmp_path / "slides" / "slide_01.jpg", "400x300")
    bad = tmp_path / "slides" / "slide_02.jpg"
    bad.write_text("<html>error</html>")
    assert [f.name for f in shrink_slides([good, bad], tmp_path / "frames")] == ["slide_01.jpg"]
    result = process_media(MediaKind.image, None, good, [bad], tmp_path, transcriber=FakeTranscriber())
    assert result.frame_paths == [good], "the thumbnail stands in when no slide could be read"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_video_frames_and_slides_share_one_image_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sift.media as media

    frames = [tmp_path / f"frame_{i:02d}.jpg" for i in range(MAX_FRAMES)]
    monkeypatch.setattr(media, "probe", lambda video: (60.0, False))
    monkeypatch.setattr(media, "extract_frames", lambda video, duration, out: frames)
    slides = [_image(tmp_path / "slides" / f"slide_{i:02d}.jpg", "400x300") for i in range(1, 10)]
    result = process_media(MediaKind.video, tmp_path / "v.mp4", None, slides, tmp_path, transcriber=FakeTranscriber())
    assert len(result.frame_paths) == MAX_IMAGES
    assert result.frame_paths[:MAX_FRAMES] == frames


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.parametrize(("ext", "frames"), [("png", "1"), ("gif", "4")])
def test_a_slide_of_any_format_becomes_one_jpeg_frame(tmp_path: Path, ext: str, frames: str) -> None:
    slide = tmp_path / "slides" / f"slide_01.{ext}"
    slide.parent.mkdir(parents=True)
    source = ["-f", "lavfi", "-i", "testsrc=size=1500x900:rate=4", "-frames:v", frames]
    subprocess.run(["ffmpeg", "-v", "error", *source, str(slide)], check=True)
    [frame] = shrink_slides([slide], tmp_path / "frames")
    assert frame.name == "slide_01.jpg" and frame.read_bytes().startswith(b"\xff\xd8\xff")
    assert _size(frame) == f"{SLIDE_LONG_EDGE},614"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_a_file_with_no_picture_has_no_image_size(tmp_path: Path) -> None:
    sound = tmp_path / "sound.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=0.1", str(sound)], check=True)
    with pytest.raises(ProcessingError) as e:
        image_size(sound)
    assert e.value.kind is FailureKind.unsupported_url and not e.value.retryable
    assert e.value.message == "sound.wav holds no picture."

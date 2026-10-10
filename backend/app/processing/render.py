"""Render the edit decision list into an MP4 (H.264 + AAC).

Two strategies, chosen per job:

* **MoviePy** – cuts the source into sub-clips (``subclipped``) and joins them with
  ``concatenate_videoclips``. Frames are streamed through FFmpeg one at a time, so
  the video is never fully loaded into RAM. Used for typical short clips.
* **FFmpeg filter graph** – a single ``trim/atrim -> concat`` pass. Faster and
  lighter for long sources or plans with many segments.

Both re-encode (no blind stream-copy), which gives frame-accurate cuts and clean
timestamps even for variable-frame-rate phone footage. Output is written to a
temporary name and only promoted after FFprobe validates it.
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import JobAborted
from app.processing.edit_plan import EditPlan
from app.processing.media import FFmpegError, MediaInfo, probe

log = logging.getLogger("splice.render")

QUALITY = {
    #           crf  x264 preset  audio bitrate
    "draft": ("30", "veryfast", "96k"),
    "balanced": ("23", "faster", "128k"),
    "high": ("19", "medium", "192k"),
}
RESOLUTION_SHORT_SIDE = {"1080p": 1080, "720p": 720, "480p": 480}
PREVIEW_SHORT_SIDE = 480


@dataclass(frozen=True)
class RenderOptions:
    resolution: str = "original"
    quality: str = "balanced"
    keep_audio: bool = True
    mode: str = "final"  # "preview" forces <=480p draft quality for speed
    engine: str = "auto"  # auto | moviepy | ffmpeg


@dataclass(frozen=True)
class RenderResult:
    engine: str
    width: int | None
    height: int | None
    duration: float
    size_bytes: int


AbortCheck = Callable[[], None]
ProgressFn = Callable[[float], None]


def target_size(width: int | None, height: int | None, options: RenderOptions) -> tuple[int, int] | None:
    """Output frame size (even numbers), or None to keep the source size."""
    if not width or not height:
        return None
    short_target = PREVIEW_SHORT_SIDE if options.mode == "preview" else RESOLUTION_SHORT_SIDE.get(options.resolution)
    if options.mode == "preview" and options.resolution in RESOLUTION_SHORT_SIDE:
        short_target = min(short_target, RESOLUTION_SHORT_SIDE[options.resolution])
    short = min(width, height)
    if short_target is None or short <= short_target:
        # still force even dimensions for yuv420p
        if width % 2 == 0 and height % 2 == 0:
            return None
        return width - width % 2, height - height % 2
    scale = short_target / short
    w, h = int(round(width * scale / 2) * 2), int(round(height * scale / 2) * 2)
    return max(2, w), max(2, h)


def choose_engine(plan: EditPlan, options: RenderOptions) -> str:
    if options.engine in ("moviepy", "ffmpeg"):
        return options.engine
    return "moviepy" if len(plan.retained) <= 40 and plan.source_duration <= 180 else "ffmpeg"


def _quality(options: RenderOptions) -> tuple[str, str, str]:
    return QUALITY["draft" if options.mode == "preview" else options.quality]


def _render_moviepy(
    src: Path,
    dst: Path,
    plan: EditPlan,
    info: MediaInfo,
    options: RenderOptions,
    size: tuple[int, int] | None,
    abort: AbortCheck,
    progress: ProgressFn,
    work_dir: Path,
) -> None:
    from moviepy import VideoFileClip, concatenate_videoclips
    from proglog import ProgressBarLogger

    class _Logger(ProgressBarLogger):
        def bars_callback(self, bar, attr, value, old_value=None):
            abort()  # raising here stops MoviePy mid-render
            if bar == "frame_index" and attr == "index":
                total = self.bars[bar].get("total") or 0
                if total:
                    progress(min(1.0, value / total))

    crf, preset, abitrate = _quality(options)
    fps = info.fps if info.fps and info.fps <= 120 else 30.0
    source = VideoFileClip(str(src), audio=options.keep_audio)
    clips = []
    try:
        # Container duration can exceed the decodable stream by a few ms; never ask past the end.
        limit = source.duration
        clips = [
            source.subclipped(d.source_start, min(d.source_end, limit))
            for d in plan.retained
            if min(d.source_end, limit) - d.source_start > 0.01
        ]
        final = concatenate_videoclips(clips, method="chain") if len(clips) > 1 else clips[0]
        if size:
            final = final.resized(new_size=size)
        final.write_videofile(
            str(dst),
            fps=fps,
            codec="libx264",
            audio=options.keep_audio,
            audio_codec="aac",
            audio_bitrate=abitrate,
            preset=preset,
            threads=2,
            ffmpeg_params=["-crf", crf, "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
            temp_audiofile=str(work_dir / "render_audio.m4a"),
            logger=_Logger(),
        )
    finally:
        for c in clips:
            c.close()
        source.close()


def build_ffmpeg_filter(plan: EditPlan, keep_audio: bool, size: tuple[int, int] | None) -> str:
    parts: list[str] = []
    labels: list[str] = []
    for i, d in enumerate(plan.retained):
        parts.append(f"[0:v:0]trim=start={d.source_start:.3f}:end={d.source_end:.3f},setpts=PTS-STARTPTS[v{i}]")
        labels.append(f"[v{i}]")
        if keep_audio:
            parts.append(f"[0:a:0]atrim=start={d.source_start:.3f}:end={d.source_end:.3f},asetpts=PTS-STARTPTS[a{i}]")
            labels.append(f"[a{i}]")
    n = len(plan.retained)
    tail = "[vcat]" + ("[aout]" if keep_audio else "")
    parts.append(f"{''.join(labels)}concat=n={n}:v=1:a={1 if keep_audio else 0}{tail}")
    scale = f"scale={size[0]}:{size[1]}:flags=bicubic," if size else ""
    parts.append(f"[vcat]{scale}format=yuv420p[vout]")
    return ";\n".join(parts)


def _render_ffmpeg(
    src: Path,
    dst: Path,
    plan: EditPlan,
    info: MediaInfo,
    options: RenderOptions,
    size: tuple[int, int] | None,
    abort: AbortCheck,
    progress: ProgressFn,
    work_dir: Path,
    timeout: float,
) -> None:
    crf, preset, abitrate = _quality(options)
    script = work_dir / "filter_graph.txt"
    script.write_text(build_ffmpeg_filter(plan, options.keep_audio, size), encoding="utf-8")
    fps = info.fps if info.fps and info.fps <= 120 else 30.0
    args = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-filter_complex_script",
        str(script),
        "-map",
        "[vout]",
    ]
    if options.keep_audio:
        args += ["-map", "[aout]", "-c:a", "aac", "-b:a", abitrate]
    else:
        args += ["-an"]
    args += [
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        crf,
        "-r",
        f"{fps:.3f}",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(dst),
    ]
    expected = max(plan.output_duration, 0.001)
    deadline = time.monotonic() + timeout
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            abort()
            if time.monotonic() > deadline:
                raise JobAborted("timeout")
            if line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    progress(min(1.0, int(line.split("=", 1)[1]) / 1e6 / expected))
                except ValueError:
                    pass
        proc.wait(timeout=max(1.0, deadline - time.monotonic()))
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    stderr = proc.stderr.read() if proc.stderr else ""
    if proc.returncode != 0:
        tail = "\n".join(stderr.strip().splitlines()[-8:])
        log.warning("ffmpeg render failed", extra={"returncode": proc.returncode, "stderr_tail": tail})
        raise FFmpegError(f"render failed (exit {proc.returncode})", tail)


def render(
    src: Path,
    out_path: Path,
    plan: EditPlan,
    info: MediaInfo,
    options: RenderOptions,
    work_dir: Path,
    timeout: float,
    abort: AbortCheck | None = None,
    progress: ProgressFn | None = None,
) -> RenderResult:
    """Render ``plan`` from ``src`` to ``out_path`` and validate the result with FFprobe."""
    abort = abort or (lambda: None)
    progress = progress or (lambda _p: None)
    size = target_size(info.width, info.height, options)
    engine = choose_engine(plan, options)
    partial = out_path.with_name(out_path.stem + ".partial.mp4")
    partial.unlink(missing_ok=True)
    try:
        if engine == "moviepy":
            _render_moviepy(src, partial, plan, info, options, size, abort, progress, work_dir)
        else:
            _render_ffmpeg(src, partial, plan, info, options, size, abort, progress, work_dir, timeout)
        out_info = validate_output(partial, plan.output_duration, options.keep_audio)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        (work_dir / "render_audio.m4a").unlink(missing_ok=True)
        (work_dir / "filter_graph.txt").unlink(missing_ok=True)
    partial.replace(out_path)
    progress(1.0)
    return RenderResult(engine, out_info.width, out_info.height, out_info.duration, out_path.stat().st_size)


def validate_output(path: Path, expected_duration: float, expect_audio: bool) -> MediaInfo:
    """FFprobe the rendered file: it must be a readable H.264 MP4 of the planned length."""
    if not path.exists() or path.stat().st_size == 0:
        raise FFmpegError("render produced no output file")
    info = probe(path)
    if not info.has_video:
        raise FFmpegError("rendered file has no video stream")
    if expect_audio and not info.has_audio:
        raise FFmpegError("rendered file is missing its audio stream")
    tolerance = max(0.35, expected_duration * 0.03)
    if abs(info.duration - expected_duration) > tolerance:
        raise FFmpegError(f"rendered duration {info.duration:.2f}s differs from planned {expected_duration:.2f}s")
    return info

"""FFmpeg-backed tests: probing, audio extraction and both render engines."""

import pytest
from media_factory import HAS_FFMPEG, audio_only_file, silent_video_no_audio, tone_video

from app.core.errors import MediaError
from app.processing.audio import extract_audio, load_wav
from app.processing.edit_plan import PlanConfig, build_edit_plan
from app.processing.media import probe, validate_source
from app.processing.render import RenderOptions, build_ffmpeg_filter, render, target_size
from app.processing.silence import detect_silence

pytestmark = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")

PATTERN = [("tone", 1.5), ("silence", 2.0), ("tone", 1.5), ("silence", 1.0), ("tone", 1.0)]


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return tone_video(tmp_path_factory.mktemp("media") / "sample.mp4", PATTERN)


def test_probe_reports_streams(sample):
    info = probe(sample)
    assert info.has_video and info.has_audio
    assert (info.width, info.height) == (320, 240)
    assert info.fps == pytest.approx(25.0)
    assert info.duration == pytest.approx(7.0, abs=0.1)
    validate_source(info, max_duration=60)


def test_validation_rejects_bad_media(tmp_path):
    no_audio = probe(silent_video_no_audio(tmp_path / "mute.mp4"))
    with pytest.raises(MediaError) as e:
        validate_source(no_audio, 60)
    assert e.value.code == "no_audio_stream"

    audio_only = probe(audio_only_file(tmp_path / "voice.mp4"))
    with pytest.raises(MediaError) as e:
        validate_source(audio_only, 60)
    assert e.value.code == "no_video_stream"

    garbage = tmp_path / "fake.mp4"
    garbage.write_bytes(b"definitely not a video" * 100)
    with pytest.raises(MediaError) as e:
        probe(garbage)
    assert e.value.code == "unreadable_media"


def test_too_long_rejected(sample):
    with pytest.raises(MediaError) as e:
        validate_source(probe(sample), max_duration=5)
    assert e.value.code == "too_long"


def test_extracted_audio_finds_the_two_gaps(sample, tmp_path):
    wav = extract_audio(sample, tmp_path / "a.wav", timeout=60)
    samples, sr = load_wav(wav)
    assert sr == 16_000
    silences = detect_silence(samples, sr, -40.0, 0.5)
    assert len(silences) == 2
    assert silences[0].start == pytest.approx(1.5, abs=0.1)
    assert silences[0].end == pytest.approx(3.5, abs=0.1)


@pytest.mark.parametrize("engine", ["moviepy", "ffmpeg"])
def test_render_engines_produce_valid_mp4(sample, tmp_path, engine):
    samples, sr = load_wav(extract_audio(sample, tmp_path / "a.wav", timeout=60))
    info = probe(sample)
    plan = build_edit_plan(info.duration, detect_silence(samples, sr, -40.0, 0.5), PlanConfig(0.1, 0.1, 0.2))
    out = tmp_path / f"out-{engine}.mp4"
    progress: list[float] = []
    result = render(sample, out, plan, info, RenderOptions(engine=engine), tmp_path, timeout=120, progress=progress.append)
    assert result.engine == engine
    out_info = probe(out)
    assert out_info.has_video and out_info.has_audio
    assert out_info.duration == pytest.approx(plan.output_duration, abs=0.35)
    assert out_info.duration < info.duration - 2.0  # ~2.6s of silence removed
    assert out_info.video_codec == "h264" and out_info.audio_codec == "aac"
    assert progress and progress[-1] == 1.0
    assert not list(tmp_path.glob("*.partial.mp4"))


def test_preview_mode_downscales_and_mutes(sample, tmp_path):
    info = probe(sample)
    plan = build_edit_plan(info.duration, [], PlanConfig())
    opts = RenderOptions(resolution="original", mode="preview", keep_audio=False, engine="ffmpeg")
    render(sample, tmp_path / "p.mp4", plan, info, opts, tmp_path, timeout=60)
    out = probe(tmp_path / "p.mp4")
    assert not out.has_audio
    assert min(out.width, out.height) <= 480


def test_target_size():
    assert target_size(1920, 1080, RenderOptions(resolution="720p")) == (1280, 720)
    assert target_size(1080, 1920, RenderOptions(resolution="720p")) == (720, 1280)  # portrait
    assert target_size(640, 360, RenderOptions(resolution="1080p")) is None  # never upscale
    assert target_size(1920, 1080, RenderOptions(mode="preview")) == (854, 480)
    assert target_size(641, 361, RenderOptions()) == (640, 360)  # even dims for yuv420p


def test_ffmpeg_filter_graph_shape():
    plan = build_edit_plan(10.0, [], PlanConfig())
    graph = build_ffmpeg_filter(plan, keep_audio=True, size=(640, 360))
    assert "concat=n=1:v=1:a=1" in graph and "scale=640:360" in graph

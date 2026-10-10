import numpy as np
import pytest

from app.processing.silence import (
    DB_FLOOR,
    Interval,
    detect_silence,
    frame_rms,
    merge_intervals,
    to_dbfs,
    waveform_envelope,
)

SR = 16_000


def tone(seconds: float, amp: float = 0.5, freq: float = 220.0) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def quiet(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), dtype=np.float32)


def detect(samples, threshold=-40.0, min_silence=0.5):
    return detect_silence(samples, SR, threshold, min_silence)


# ---- RMS / dBFS -------------------------------------------------------------------
def test_rms_of_full_scale_sine_is_one_over_root_two():
    rms = frame_rms(tone(1.0, amp=1.0), SR)
    assert np.allclose(rms[:-3], 1 / np.sqrt(2), atol=0.02)


def test_dbfs_reference_points_and_safe_log():
    assert to_dbfs(1.0) == pytest.approx(0.0)
    assert to_dbfs(0.1) == pytest.approx(-20.0)
    assert to_dbfs(0.0) == pytest.approx(DB_FLOOR)  # no -inf, no warning
    assert to_dbfs(np.array([1e-12]))[0] == pytest.approx(DB_FLOOR)


def test_half_amplitude_sine_is_about_minus_9_dbfs():
    db = to_dbfs(frame_rms(tone(1.0, amp=0.5), SR))
    assert np.median(db) == pytest.approx(-9.03, abs=0.2)


def test_frame_rms_handles_audio_shorter_than_one_frame():
    rms = frame_rms(tone(0.005), SR)
    assert rms.shape == (1,)


# ---- detection ----------------------------------------------------------------------
def test_leading_silence_starts_at_zero():
    s = detect(np.concatenate([quiet(1.0), tone(1.0)]))
    assert len(s) == 1
    assert s[0].start == 0.0
    assert s[0].end == pytest.approx(1.0, abs=0.03)


def test_trailing_silence_ends_at_duration():
    s = detect(np.concatenate([tone(1.0), quiet(1.2)]))
    assert len(s) == 1
    assert s[0].start == pytest.approx(1.0, abs=0.03)
    assert s[0].end == pytest.approx(2.2)


def test_long_internal_silence_detected():
    s = detect(np.concatenate([tone(1.0), quiet(2.0), tone(1.0)]))
    assert len(s) == 1
    assert s[0].start == pytest.approx(1.0, abs=0.03)
    assert s[0].end == pytest.approx(3.0, abs=0.03)


def test_short_pause_is_retained():
    s = detect(np.concatenate([tone(1.0), quiet(0.3), tone(1.0)]), min_silence=0.5)
    assert s == []


def test_continuous_speech_has_no_silence():
    assert detect(tone(3.0)) == []


def test_entirely_silent_audio_is_one_interval():
    s = detect(quiet(2.0))
    assert s == [Interval(0.0, 2.0)]


def test_very_short_audio():
    assert detect(quiet(0.05), min_silence=0.5) == []
    assert detect(quiet(0.05), min_silence=0.02) == [Interval(0.0, 0.05)]


def test_empty_input_returns_nothing():
    assert detect(np.zeros(0, dtype=np.float32)) == []


@pytest.mark.parametrize(
    ("samples", "sr", "min_sil"),
    [
        (np.array([0.0, np.nan]), SR, 0.5),
        (np.array([0.0, np.inf]), SR, 0.5),
        (np.zeros((2, 2, 2)), SR, 0.5),
        (np.zeros(10), 0, 0.5),
        (np.zeros(10), SR, 0.0),
    ],
)
def test_invalid_input_raises(samples, sr, min_sil):
    with pytest.raises(ValueError):
        detect_silence(samples, sr, -40.0, min_sil)


def test_threshold_controls_what_counts_as_silence():
    audio = np.concatenate([tone(1.0, amp=0.5), tone(1.0, amp=0.003), tone(1.0, amp=0.5)])  # middle ≈ -53 dBFS
    assert len(detect(audio, threshold=-40.0)) == 1
    assert detect(audio, threshold=-60.0) == []


def test_brief_click_inside_silence_does_not_split_it():
    click = tone(0.02, amp=0.8)
    s = detect(np.concatenate([tone(1.0), quiet(0.8), click, quiet(0.8), tone(1.0)]))
    assert len(s) == 1
    assert s[0].duration == pytest.approx(1.62, abs=0.06)


def test_stereo_input_is_downmixed():
    mono = np.concatenate([tone(1.0), quiet(1.0), tone(1.0)])
    stereo = np.stack([mono, mono], axis=1)
    assert len(detect_silence(stereo, SR, -40.0, 0.5)) == 1


def test_merge_intervals():
    merged = merge_intervals([Interval(2, 3), Interval(0, 1), Interval(1.05, 1.5)], max_gap=0.1)
    assert merged == [Interval(0, 1.5), Interval(2, 3)]


def test_waveform_envelope_is_bounded():
    step, env = waveform_envelope(np.concatenate([tone(5.0), quiet(5.0)]), SR, max_points=100)
    assert len(env) <= 100
    assert step > 0
    assert max(env) > -15 and min(env) == pytest.approx(DB_FLOOR)

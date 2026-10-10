"""Configuration, settings schema, state machine, job store and rate limiter."""

import itertools
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.core.config import settings_from_env
from app.core.rate_limit import SlidingWindowLimiter
from app.schemas.jobs import EditSettings, JobStatus
from app.services.job_store import JobStore, iso, utcnow
from app.services.state_machine import InvalidTransition, assert_transition, can_transition


# ---- configuration -------------------------------------------------------------------
def test_config_defaults_and_lists():
    s = settings_from_env({"FRONTEND_ORIGINS": "https://a.app, https://b.app", "MAX_UPLOAD_MB": "25"})
    assert s.frontend_origins == ["https://a.app", "https://b.app"]
    assert s.max_upload_bytes == 25 * 1024 * 1024


@pytest.mark.parametrize(
    "env",
    [
        {"MAX_UPLOAD_MB": "0"},
        {"MAX_UPLOAD_MB": "lots"},
        {"WHISPER_ENGINE": "gpt"},
        {"WHISPER_ALLOWED_MODELS": "tiny,large-v3"},
        {"WHISPER_MODEL": "base", "WHISPER_ALLOWED_MODELS": "tiny"},
        {"LOG_LEVEL": "LOUD"},
    ],
)
def test_invalid_config_fails_fast_with_readable_message(env):
    with pytest.raises(RuntimeError, match="Invalid SPLICE configuration"):
        settings_from_env(env)


# ---- edit settings -------------------------------------------------------------------
def test_edit_settings_defaults_valid():
    s = EditSettings()
    assert s.mode == "final" and s.language is None


def test_edit_settings_rejects_unknown_and_out_of_range():
    with pytest.raises(ValidationError):
        EditSettings(silence_threshold_db=5)
    with pytest.raises(ValidationError):
        EditSettings(made_up=True)
    with pytest.raises(ValidationError):
        EditSettings(padding_before=0.4, padding_after=0.4, min_silence_duration=0.5)
    with pytest.raises(ValidationError):
        EditSettings(language="english!")


def test_language_auto_maps_to_none():
    assert EditSettings(language="auto").language is None
    assert EditSettings(language="EN").language == "en"


# ---- state machine ---------------------------------------------------------------------
def test_happy_path_transitions_are_allowed():
    path = [
        JobStatus.QUEUED,
        JobStatus.VALIDATING,
        JobStatus.EXTRACTING_AUDIO,
        JobStatus.TRANSCRIBING,
        JobStatus.DETECTING_SILENCE,
        JobStatus.GENERATING_EDIT_PLAN,
        JobStatus.RENDERING,
        JobStatus.COMPLETED,
    ]
    for a, b in itertools.pairwise(path):
        assert_transition(a, b)


def test_illegal_transitions_rejected():
    with pytest.raises(InvalidTransition):
        assert_transition(JobStatus.QUEUED, JobStatus.COMPLETED)
    with pytest.raises(InvalidTransition):
        assert_transition(JobStatus.FAILED, JobStatus.RENDERING)
    assert not can_transition(JobStatus.EXPIRED, JobStatus.QUEUED)


def test_rerender_path_allowed():
    assert can_transition(JobStatus.COMPLETED, JobStatus.QUEUED)
    assert can_transition(JobStatus.QUEUED, JobStatus.DETECTING_SILENCE)


def test_any_active_state_can_fail_or_cancel():
    for s in (JobStatus.VALIDATING, JobStatus.TRANSCRIBING, JobStatus.RENDERING):
        assert can_transition(s, JobStatus.FAILED)
        assert can_transition(s, JobStatus.CANCELLED)


# ---- job store -------------------------------------------------------------------------
def test_store_create_token_and_transition(tmp_path):
    store = JobStore(tmp_path / "db.sqlite", ttl_minutes=60)
    rec, token = store.create("clip.mp4", {"mode": "final"})
    assert len(rec.id) == 32 and rec.status == JobStatus.QUEUED
    assert rec.token_matches(token) and not rec.token_matches("nope") and not rec.token_matches(None)
    assert token not in rec.token_hash  # only the hash is stored
    rec = store.transition(rec.id, JobStatus.VALIDATING)
    assert rec.status == JobStatus.VALIDATING
    with pytest.raises(InvalidTransition):
        store.transition(rec.id, JobStatus.COMPLETED)
    assert store.count_active() == 1


def test_store_expiry_detection(tmp_path):
    store = JobStore(tmp_path / "db.sqlite", ttl_minutes=60)
    rec, _ = store.create("a.mp4", {})
    assert not rec.is_expired and store.expired_candidates() == []
    store.update(rec.id, expires_at=iso(utcnow() - timedelta(seconds=1)))
    assert store.get(rec.id).is_expired
    assert store.expired_candidates() == [rec.id]


# ---- rate limiter --------------------------------------------------------------------------
def test_sliding_window_limiter():
    lim = SlidingWindowLimiter(limit=2, window_seconds=10)
    assert lim.allow("ip", now=0)[0]
    assert lim.allow("ip", now=1)[0]
    allowed, retry = lim.allow("ip", now=2)
    assert not allowed and retry == 8
    assert lim.allow("other", now=2)[0]
    assert lim.allow("ip", now=11)[0]


def test_limiter_disabled_when_zero():
    lim = SlidingWindowLimiter(limit=0)
    assert all(lim.allow("ip")[0] for _ in range(100))

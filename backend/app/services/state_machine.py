"""Job lifecycle state machine.

    queued -> validating -> extracting_audio -> transcribing -> detecting_silence
           -> generating_edit_plan -> rendering -> completed

Any active state may move to failed or cancelled. A completed job can be
re-rendered with new settings (completed -> detecting_silence), reusing the
cached audio and transcript. Finished jobs eventually become expired.
"""

from __future__ import annotations

from app.schemas.jobs import JobStatus as S

ACTIVE = frozenset(
    {
        S.QUEUED,
        S.VALIDATING,
        S.EXTRACTING_AUDIO,
        S.TRANSCRIBING,
        S.DETECTING_SILENCE,
        S.GENERATING_EDIT_PLAN,
        S.RENDERING,
    }
)
TERMINAL = frozenset({S.COMPLETED, S.FAILED, S.CANCELLED, S.EXPIRED})

_PIPELINE = [
    S.QUEUED,
    S.VALIDATING,
    S.EXTRACTING_AUDIO,
    S.TRANSCRIBING,
    S.DETECTING_SILENCE,
    S.GENERATING_EDIT_PLAN,
    S.RENDERING,
    S.COMPLETED,
]

TRANSITIONS: dict[S, frozenset[S]] = {
    s: frozenset({_PIPELINE[i + 1], S.FAILED, S.CANCELLED, S.EXPIRED}) for i, s in enumerate(_PIPELINE[:-1])
}
TRANSITIONS[S.COMPLETED] = frozenset({S.QUEUED, S.EXPIRED})  # queued again for a re-render
TRANSITIONS[S.FAILED] = frozenset({S.EXPIRED})
TRANSITIONS[S.CANCELLED] = frozenset({S.EXPIRED})
TRANSITIONS[S.EXPIRED] = frozenset()
# A re-render skips straight from queued to silence detection.
TRANSITIONS[S.QUEUED] = TRANSITIONS[S.QUEUED] | {S.DETECTING_SILENCE}

STAGE_LABELS = {
    S.QUEUED: "Waiting in queue",
    S.VALIDATING: "Validating video",
    S.EXTRACTING_AUDIO: "Extracting audio",
    S.TRANSCRIBING: "Transcribing speech",
    S.DETECTING_SILENCE: "Detecting silence",
    S.GENERATING_EDIT_PLAN: "Generating edit decisions",
    S.RENDERING: "Rendering output",
    S.COMPLETED: "Ready to download",
    S.FAILED: "Failed",
    S.CANCELLED: "Cancelled",
    S.EXPIRED: "Expired",
}


class InvalidTransition(ValueError):
    pass


def can_transition(current: S, new: S) -> bool:
    return new in TRANSITIONS.get(current, frozenset())


def assert_transition(current: S, new: S) -> None:
    if not can_transition(current, new):
        raise InvalidTransition(f"cannot move job from {current.value} to {new.value}")

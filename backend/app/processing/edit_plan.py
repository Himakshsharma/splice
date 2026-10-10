"""Edit decision engine.

Turns detected silence (and, optionally, Whisper word timings) into a validated
edit decision list (EDL). The EDL is the single source of truth: the renderer
renders exactly its ``retain`` entries and the dashboard displays exactly this list.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from app.processing.silence import Interval

# A removal shorter than this is not worth a visible jump cut.
MIN_CUT_SECONDS = 0.08
# Breathing room kept around words Whisper heard when protecting quiet speech.
SPEECH_GUARD_SECONDS = 0.05
_EPS = 1e-6


@dataclass(frozen=True)
class PlanConfig:
    padding_before: float = 0.12
    padding_after: float = 0.18
    min_segment_duration: float = 0.25
    max_output_duration: float | None = None
    protect_speech: bool = True


@dataclass
class EditDecision:
    index: int
    decision: Literal["retain", "remove"]
    reason: str
    source_start: float
    source_end: float
    duration: float
    output_start: float | None
    output_end: float | None


@dataclass
class EditPlan:
    source_duration: float
    decisions: list[EditDecision]
    warnings: list[str] = field(default_factory=list)

    @property
    def retained(self) -> list[EditDecision]:
        return [d for d in self.decisions if d.decision == "retain"]

    @property
    def output_duration(self) -> float:
        return round(sum(d.duration for d in self.retained), 3)

    @property
    def removed_duration(self) -> float:
        return round(self.source_duration - self.output_duration, 3)

    @property
    def cut_count(self) -> int:
        return sum(1 for d in self.decisions if d.decision == "remove")

    def to_dict(self) -> dict:
        return {
            "source_duration": self.source_duration,
            "decisions": [asdict(d) for d in self.decisions],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict) -> EditPlan:
        return cls(
            source_duration=float(data["source_duration"]),
            decisions=[EditDecision(**d) for d in data["decisions"]],
            warnings=list(data.get("warnings", [])),
        )


def normalize_intervals(intervals: list[Interval], duration: float) -> list[Interval]:
    """Clamp to [0, duration], drop empty/invalid ones, sort and merge overlaps."""
    clean: list[Interval] = []
    for iv in intervals:
        start = min(max(0.0, float(iv.start)), duration)
        end = min(max(0.0, float(iv.end)), duration)
        if end - start > _EPS:
            clean.append(Interval(start, end))
    clean.sort(key=lambda i: i.start)
    merged: list[Interval] = []
    for iv in clean:
        if merged and iv.start <= merged[-1].end + _EPS:
            merged[-1] = Interval(merged[-1].start, max(merged[-1].end, iv.end))
        else:
            merged.append(iv)
    return merged


def _subtract(base: Interval, holes: list[Interval]) -> list[Interval]:
    pieces = [base]
    for hole in holes:
        nxt: list[Interval] = []
        for p in pieces:
            if hole.end <= p.start or hole.start >= p.end:
                nxt.append(p)
                continue
            if hole.start > p.start:
                nxt.append(Interval(p.start, hole.start))
            if hole.end < p.end:
                nxt.append(Interval(hole.end, p.end))
        pieces = nxt
    return pieces


def build_edit_plan(
    duration: float,
    silences: list[Interval],
    config: PlanConfig,
    speech_spans: list[Interval] | None = None,
) -> EditPlan:
    """Build a validated EDL for a source of ``duration`` seconds.

    * ``silences`` – quiet intervals from the energy detector.
    * ``speech_spans`` – Whisper word (or segment) timings. When ``protect_speech``
      is on, nothing inside them (plus a small guard) is ever cut, which rescues
      quiet speech the energy detector mistook for silence.
    """
    if duration <= 0:
        raise ValueError("duration must be positive")
    duration = round(float(duration), 3)
    warnings: list[str] = []
    silences = normalize_intervals(silences, duration)

    # 1. Shrink each silence by the configured padding to get candidate cuts.
    cuts: list[tuple[Interval, str]] = []
    for s in silences:
        start = s.start if s.start <= _EPS else s.start + config.padding_after
        end = s.end if s.end >= duration - _EPS else s.end - config.padding_before
        if end - start >= MIN_CUT_SECONDS:
            cuts.append((Interval(start, end), "silence"))

    # 2. Protect words Whisper heard inside "silent" regions.
    protected_seconds = 0.0
    if config.protect_speech and speech_spans:
        guards = normalize_intervals(
            [Interval(sp.start - SPEECH_GUARD_SECONDS, sp.end + SPEECH_GUARD_SECONDS) for sp in speech_spans],
            duration,
        )
        protected: list[tuple[Interval, str]] = []
        for cut, reason in cuts:
            pieces = [p for p in _subtract(cut, guards) if p.duration >= MIN_CUT_SECONDS]
            protected_seconds += cut.duration - sum(p.duration for p in pieces)
            protected.extend((p, reason) for p in pieces)
        cuts = protected
        if protected_seconds > 0.05:
            warnings.append(f"Kept {protected_seconds:.1f}s of quiet audio because Whisper detected speech there.")

    # 3. Retained segments are the complement of the cuts.
    regions: list[list] = []  # [start, end, decision, reason]
    cursor = 0.0
    for cut, reason in sorted(cuts, key=lambda c: c[0].start):
        if cut.start > cursor + _EPS:
            regions.append([cursor, cut.start, "retain", "speech"])
        regions.append([cut.start, cut.end, "remove", reason])
        cursor = cut.end
    if cursor < duration - _EPS:
        regions.append([cursor, duration, "retain", "speech"])

    # 4. Drop micro-segments (clicks, single syllables of noise) between cuts.
    retained_idx = [i for i, r in enumerate(regions) if r[2] == "retain"]
    if config.min_segment_duration > 0 and len(retained_idx) > 1:
        for i in retained_idx:
            if regions[i][1] - regions[i][0] < config.min_segment_duration:
                regions[i][2], regions[i][3] = "remove", "too_short"
        if not any(r[2] == "retain" for r in regions):  # never drop everything this way
            longest = max(retained_idx, key=lambda i: regions[i][1] - regions[i][0])
            regions[longest][2], regions[longest][3] = "retain", "speech"

    # 5. Fully silent input: keep the original rather than producing an empty video.
    if not any(r[2] == "retain" for r in regions):
        warnings.append("No speech was detected above the silence threshold, so the original video was kept.")
        regions = [[0.0, duration, "retain", "no_speech_detected"]]

    # 6. Optional cap on output length (trims from the end).
    if config.max_output_duration is not None:
        budget = config.max_output_duration
        capped: list[list] = []
        for start, end, decision, reason in regions:
            if decision == "retain":
                length = end - start
                if budget <= _EPS:
                    capped.append([start, end, "remove", "max_duration"])
                    continue
                if length > budget:
                    capped.append([start, start + budget, "retain", reason])
                    capped.append([start + budget, end, "remove", "max_duration"])
                    budget = 0.0
                    continue
                budget -= length
            capped.append([start, end, decision, reason])
        if any(r[3] == "max_duration" for r in capped):
            warnings.append(f"Output was trimmed to the {config.max_output_duration:.0f}s maximum duration.")
        regions = capped

    # 7. Merge neighbouring regions with the same decision and drop zero-length ones.
    merged: list[list] = []
    for start, end, decision, reason in regions:
        if end - start <= _EPS:
            continue
        if merged and merged[-1][2] == decision and abs(merged[-1][1] - start) <= _EPS:
            merged[-1][1] = end
            if reason not in merged[-1][3].split("+"):
                merged[-1][3] += f"+{reason}"
        else:
            merged.append([start, end, decision, reason])

    # 8. Assign output timestamps.
    decisions: list[EditDecision] = []
    out_cursor = 0.0
    for idx, (start, end, decision, reason) in enumerate(merged):
        s, e = round(start, 3), round(end, 3)
        if decision == "retain":
            o_start, o_end = round(out_cursor, 3), round(out_cursor + (e - s), 3)
            out_cursor += e - s
        else:
            o_start = o_end = None
        decisions.append(EditDecision(idx, decision, reason, s, e, round(e - s, 3), o_start, o_end))

    plan = EditPlan(source_duration=duration, decisions=decisions, warnings=warnings)
    validate_plan(plan)
    return plan


def validate_plan(plan: EditPlan) -> None:
    """Assert EDL invariants; raises ValueError if any is violated."""
    if not plan.decisions:
        raise ValueError("edit plan is empty")
    if not plan.retained:
        raise ValueError("edit plan retains nothing")
    prev_end = 0.0
    for d in plan.decisions:
        if d.source_start < 0 or d.source_end > plan.source_duration + 1e-3:
            raise ValueError(f"decision {d.index} is outside the media duration")
        if d.source_end - d.source_start <= 0:
            raise ValueError(f"decision {d.index} has zero or negative length")
        if abs(d.source_start - prev_end) > 2e-3:
            raise ValueError(f"decision {d.index} is not contiguous with the previous one")
        prev_end = d.source_end
    if abs(prev_end - plan.source_duration) > 2e-3:
        raise ValueError("edit plan does not cover the full source")

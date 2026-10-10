import itertools

import pytest

from app.processing.edit_plan import (
    EditDecision,
    EditPlan,
    PlanConfig,
    build_edit_plan,
    normalize_intervals,
    validate_plan,
)
from app.processing.silence import Interval

CFG = PlanConfig(padding_before=0.1, padding_after=0.2, min_segment_duration=0.25)


def kinds(plan):
    return [(d.decision, round(d.source_start, 2), round(d.source_end, 2)) for d in plan.decisions]


def test_internal_silence_is_cut_with_padding():
    plan = build_edit_plan(10.0, [Interval(3.0, 6.0)], CFG)
    assert kinds(plan) == [("retain", 0.0, 3.2), ("remove", 3.2, 5.9), ("retain", 5.9, 10.0)]
    assert plan.output_duration == pytest.approx(7.3)
    assert plan.removed_duration == pytest.approx(2.7)
    assert plan.cut_count == 1


def test_output_timestamps_are_contiguous():
    plan = build_edit_plan(10.0, [Interval(1.0, 2.0), Interval(5.0, 7.0)], CFG)
    retained = plan.retained
    assert retained[0].output_start == 0.0
    for a, b in itertools.pairwise(retained):
        assert b.output_start == pytest.approx(a.output_end)
    assert retained[-1].output_end == pytest.approx(plan.output_duration)


def test_leading_and_trailing_silence_cut_to_the_edges():
    plan = build_edit_plan(10.0, [Interval(0.0, 2.0), Interval(8.0, 10.0)], CFG)
    assert kinds(plan) == [("remove", 0.0, 1.9), ("retain", 1.9, 8.2), ("remove", 8.2, 10.0)]


def test_no_silence_keeps_everything():
    plan = build_edit_plan(5.0, [], CFG)
    assert kinds(plan) == [("retain", 0.0, 5.0)]
    assert plan.cut_count == 0


def test_all_silent_keeps_original_with_warning():
    plan = build_edit_plan(4.0, [Interval(0.0, 4.0)], CFG)
    assert kinds(plan) == [("retain", 0.0, 4.0)]
    assert plan.decisions[0].reason == "no_speech_detected"
    assert plan.warnings


def test_tiny_cuts_are_skipped():
    # silence 0.35s minus 0.3s padding = 0.05s cut -> below MIN_CUT -> not cut
    plan = build_edit_plan(5.0, [Interval(2.0, 2.35)], CFG)
    assert plan.cut_count == 0


def test_micro_segments_between_cuts_are_dropped_and_merged():
    # A 0.15s noise burst between two silences survives as a 0.45s segment once padding is
    # added (0.15 + 0.1 + 0.2), which is below the 0.5s minimum segment length.
    silences = [Interval(1.0, 3.0), Interval(3.15, 6.0)]
    plan = build_edit_plan(10.0, silences, PlanConfig(0.1, 0.2, min_segment_duration=0.5))
    removes = [d for d in plan.decisions if d.decision == "remove"]
    assert len(removes) == 1  # blip removed and neighbouring cuts merged into one
    assert "too_short" in removes[0].reason


def test_whisper_speech_protects_quiet_words():
    plan = build_edit_plan(10.0, [Interval(2.0, 8.0)], CFG, speech_spans=[Interval(4.5, 5.0)])
    retained = plan.retained
    assert any(d.source_start <= 4.5 and d.source_end >= 5.0 for d in retained)
    assert any("Whisper" in w for w in plan.warnings)


def test_protection_can_be_disabled():
    cfg = PlanConfig(0.1, 0.2, 0.25, protect_speech=False)
    plan = build_edit_plan(10.0, [Interval(2.0, 8.0)], cfg, speech_spans=[Interval(4.5, 5.0)])
    assert plan.cut_count == 1


def test_max_output_duration_trims_tail():
    cfg = PlanConfig(0.1, 0.2, 0.25, max_output_duration=4.0)
    plan = build_edit_plan(10.0, [Interval(3.0, 6.0)], cfg)
    assert plan.output_duration == pytest.approx(4.0)
    assert plan.decisions[-1].decision == "remove"
    assert "max_duration" in plan.decisions[-1].reason


def test_intervals_are_clamped_sorted_and_merged():
    out = normalize_intervals([Interval(-1, 1), Interval(8, 12), Interval(0.5, 2), Interval(5, 5)], 10.0)
    assert out == [Interval(0.0, 2), Interval(8, 10.0)]


def test_out_of_range_silence_never_produces_invalid_plan():
    plan = build_edit_plan(5.0, [Interval(-3, 1.5), Interval(4.0, 99)], CFG)
    validate_plan(plan)
    assert plan.decisions[0].source_start == 0.0
    assert plan.decisions[-1].source_end == 5.0


def test_invalid_duration():
    with pytest.raises(ValueError):
        build_edit_plan(0, [], CFG)


def test_validate_plan_rejects_gaps():
    bad = EditPlan(
        source_duration=4.0,
        decisions=[
            EditDecision(0, "retain", "speech", 0.0, 1.0, 1.0, 0.0, 1.0),
            EditDecision(1, "retain", "speech", 2.0, 4.0, 2.0, 1.0, 3.0),
        ],
    )
    with pytest.raises(ValueError):
        validate_plan(bad)


def test_round_trip_serialisation():
    plan = build_edit_plan(10.0, [Interval(3.0, 6.0)], CFG)
    again = EditPlan.from_dict(plan.to_dict())
    assert kinds(again) == kinds(plan)
    assert again.output_duration == plan.output_duration

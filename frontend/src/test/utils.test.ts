import { describe, expect, it } from "vitest";
import type { EditPlan } from "../types/api";
import { formatBytes, formatDuration, formatTimecode, humanizeReason } from "../utils/format";
import { canRerenderWith, DEFAULT_SETTINGS, validateSettings } from "../utils/settings";
import { stripFromPlan } from "../utils/strip";
import { checkFile } from "../utils/validation";

const file = (name: string, bytes: number) => ({ name, size: bytes }) as File;

describe("format", () => {
  it("formats bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(50 * 1024 * 1024)).toBe("50.0 MB");
    expect(formatBytes(-1)).toBe("—");
  });
  it("formats timecodes and durations", () => {
    expect(formatTimecode(75.4)).toBe("1:15.4");
    expect(formatTimecode(3725)).toBe("1:02:05.0");
    expect(formatTimecode(5, 2)).toBe("0:05.00");
    expect(formatDuration(4.25)).toBe("4.3s");
    expect(formatDuration(95)).toBe("1m 35s");
  });
  it("humanizes merged reasons", () => {
    expect(humanizeReason("silence+too_short")).toBe("Silence + Too short to keep");
  });
});

describe("upload validation", () => {
  it("accepts supported videos under the limit", () => {
    expect(checkFile(file("talk.MP4", 1024), 50).ok).toBe(true);
  });
  it("rejects wrong types, empty and oversized files", () => {
    expect(checkFile(file("notes.txt", 10), 50).ok).toBe(false);
    expect(checkFile(file("empty.mp4", 0), 50).message).toContain("empty");
    expect(checkFile(file("big.mov", 60 * 1024 * 1024), 50).message).toContain("50 MB");
  });
});

describe("settings", () => {
  it("defaults are valid", () => {
    expect(validateSettings(DEFAULT_SETTINGS)).toEqual([]);
  });
  it("rejects padding that swallows the minimum pause", () => {
    const errs = validateSettings({ ...DEFAULT_SETTINGS, padding_before: 0.3, padding_after: 0.3, min_silence_duration: 0.5 });
    expect(errs.length).toBe(1);
  });
  it("rejects a max output length below one second", () => {
    expect(validateSettings({ ...DEFAULT_SETTINGS, max_output_duration: 0 }).length).toBe(1);
  });
  it("only allows re-render when model and language are unchanged", () => {
    expect(canRerenderWith(DEFAULT_SETTINGS, { ...DEFAULT_SETTINGS, silence_threshold_db: -30 })).toBe(true);
    expect(canRerenderWith(DEFAULT_SETTINGS, { ...DEFAULT_SETTINGS, whisper_model: "base" })).toBe(false);
    expect(canRerenderWith(DEFAULT_SETTINGS, { ...DEFAULT_SETTINGS, language: "en" })).toBe(false);
  });
});

describe("3D strip from a real plan", () => {
  const plan: EditPlan = {
    source_duration: 4,
    output_duration: 2,
    removed_duration: 2,
    cut_count: 1,
    retained_count: 2,
    threshold_db: -40,
    decisions: [
      { index: 0, decision: "retain", reason: "speech", source_start: 0, source_end: 1, duration: 1, output_start: 0, output_end: 1 },
      { index: 1, decision: "remove", reason: "silence", source_start: 1, source_end: 3, duration: 2, output_start: null, output_end: null },
      { index: 2, decision: "retain", reason: "speech", source_start: 3, source_end: 4, duration: 1, output_start: 1, output_end: 2 },
    ],
    silences: [{ start: 1, end: 3 }],
    waveform: { seconds_per_point: 0.5, db: [-10, -12, -80, -80, -80, -80, -8, -9] },
    warnings: [],
  };
  it("maps loudness to 0..1 and decisions to keep flags", () => {
    const { levels, keep } = stripFromPlan(plan);
    expect(levels.length).toBe(8);
    expect(levels[2]).toBe(0);
    expect(levels[0]).toBeGreaterThan(0.5);
    expect(keep).toEqual([true, true, false, false, false, false, true, true]);
  });
  it("downsamples to the bar budget", () => {
    expect(stripFromPlan(plan, 4).levels.length).toBe(4);
  });
});

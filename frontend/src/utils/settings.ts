import type { EditSettings } from "../types/api";

/** Mirrors backend defaults; replaced by /api/config values once loaded. */
export const DEFAULT_SETTINGS: EditSettings = {
  silence_threshold_db: -40,
  min_silence_duration: 0.5,
  padding_before: 0.12,
  padding_after: 0.18,
  min_segment_duration: 0.25,
  max_output_duration: null,
  whisper_model: "tiny",
  language: null,
  protect_speech: true,
  output_resolution: "original",
  quality: "balanced",
  keep_audio: true,
  mode: "final",
};

export interface RangeSpec {
  key: keyof Pick<
    EditSettings,
    "silence_threshold_db" | "min_silence_duration" | "padding_before" | "padding_after" | "min_segment_duration"
  >;
  label: string;
  help: string;
  min: number;
  max: number;
  step: number;
  unit: string;
}

/** Ranges are a subset of the backend's validation limits, chosen to be useful. */
export const RANGE_SETTINGS: RangeSpec[] = [
  {
    key: "silence_threshold_db",
    label: "Silence threshold",
    help: "Audio quieter than this counts as silence. Raise it (toward −25) for noisy rooms.",
    min: -60,
    max: -20,
    step: 1,
    unit: "dBFS",
  },
  {
    key: "min_silence_duration",
    label: "Minimum pause to cut",
    help: "Shorter pauses are left alone so speech keeps its rhythm.",
    min: 0.2,
    max: 3,
    step: 0.05,
    unit: "s",
  },
  {
    key: "padding_before",
    label: "Keep before speech",
    help: "Breathing room left before someone starts talking again.",
    min: 0,
    max: 0.6,
    step: 0.01,
    unit: "s",
  },
  {
    key: "padding_after",
    label: "Keep after speech",
    help: "Room left after a sentence ends, so words aren't clipped.",
    min: 0,
    max: 0.6,
    step: 0.01,
    unit: "s",
  },
  {
    key: "min_segment_duration",
    label: "Shortest clip to keep",
    help: "Removes stray noises left between two cuts.",
    min: 0,
    max: 1.5,
    step: 0.05,
    unit: "s",
  },
];

export const LANGUAGES: { code: string | null; label: string }[] = [
  { code: null, label: "Detect automatically" },
  { code: "en", label: "English" },
  { code: "hi", label: "Hindi" },
  { code: "es", label: "Spanish" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
  { code: "pt", label: "Portuguese" },
  { code: "ja", label: "Japanese" },
  { code: "ko", label: "Korean" },
  { code: "zh", label: "Chinese" },
];

/** Client-side validation mirroring the backend's cross-field rule. Returns error messages. */
export function validateSettings(s: EditSettings): string[] {
  const errors: string[] = [];
  if (s.padding_before + s.padding_after >= s.min_silence_duration) {
    errors.push("The two padding values together must be shorter than the minimum pause, or nothing can be cut.");
  }
  if (s.max_output_duration !== null && (s.max_output_duration < 1 || !Number.isFinite(s.max_output_duration))) {
    errors.push("Maximum output length must be at least 1 second.");
  }
  return errors;
}

/** Whisper model + language are fixed after analysis; other settings can be re-rendered. */
export function canRerenderWith(original: EditSettings, next: EditSettings): boolean {
  return original.whisper_model === next.whisper_model && (original.language ?? null) === (next.language ?? null);
}

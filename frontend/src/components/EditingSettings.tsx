import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";
import type { EditSettings as Settings } from "../types/api";
import { LANGUAGES, RANGE_SETTINGS } from "../utils/settings";

interface Props {
  value: Settings;
  onChange: (next: Settings) => void;
  models: string[];
  disabled?: boolean;
  /** Whisper model and language can't change after analysis (re-render keeps the transcript). */
  analysisLocked?: boolean;
  errors: string[];
}

function fmt(v: number, unit: string) {
  return unit === "dBFS" ? `${v.toFixed(0)} dBFS` : `${v.toFixed(2)} s`;
}

export function EditingSettings({ value, onChange, models, disabled, analysisLocked, errors }: Props) {
  const [advanced, setAdvanced] = useState(false);
  const id = useId();
  const set = <K extends keyof Settings>(key: K, v: Settings[K]) => onChange({ ...value, [key]: v });

  return (
    <fieldset className="panel p-4" disabled={disabled} aria-describedby={errors.length ? `${id}-err` : undefined}>
      <legend className="sr-only">Editing settings</legend>
      <h2 className="mb-4 text-base font-semibold">Cut settings</h2>

      <div className="space-y-5">
        {RANGE_SETTINGS.map((spec) => (
          <div key={spec.key}>
            <div className="flex items-baseline justify-between gap-2">
              <label htmlFor={`${id}-${spec.key}`} className="text-sm font-medium">
                {spec.label}
              </label>
              <output htmlFor={`${id}-${spec.key}`} className="tnum text-sm text-keep-soft">
                {fmt(value[spec.key], spec.unit)}
              </output>
            </div>
            <input
              id={`${id}-${spec.key}`}
              type="range"
              className="field-range mt-2"
              min={spec.min}
              max={spec.max}
              step={spec.step}
              value={value[spec.key]}
              onChange={(e) => set(spec.key, Number(e.target.value))}
            />
            <p className="mt-1 text-xs leading-snug text-faint">{spec.help}</p>
          </div>
        ))}

        <label className="flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 accent-[var(--color-keep)]"
            checked={value.protect_speech}
            onChange={(e) => set("protect_speech", e.target.checked)}
          />
          <span>
            <span className="font-medium">Protect words Whisper hears</span>
            <span className="block text-xs text-faint">Never cut through a word, even if it was spoken quietly.</span>
          </span>
        </label>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-2 rounded-xl bg-raised p-1" role="radiogroup" aria-label="Render mode">
        {(["preview", "final"] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={value.mode === m}
            onClick={() => set("mode", m)}
            className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              value.mode === m ? "bg-keep text-[#120f22]" : "text-muted hover:text-text"
            }`}
          >
            {m === "preview" ? "Quick preview" : "Final export"}
          </button>
        ))}
      </div>
      <p className="mt-1.5 text-xs text-faint">
        {value.mode === "preview"
          ? "Renders a fast 480p draft. You can export the final version afterwards without re-analysing."
          : "Renders at the resolution and quality chosen below."}
      </p>

      <button
        type="button"
        className="mt-5 flex w-full items-center justify-between rounded-lg py-1 text-sm font-medium text-muted hover:text-text"
        aria-expanded={advanced}
        onClick={() => setAdvanced((a) => !a)}
      >
        Output and transcription
        <ChevronDown size={16} className={`transition-transform ${advanced ? "rotate-180" : ""}`} aria-hidden />
      </button>

      {advanced && (
        <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
          <label className="col-span-1 space-y-1">
            <span className="text-muted">Resolution</span>
            <select className="field-select" value={value.output_resolution} onChange={(e) => set("output_resolution", e.target.value as Settings["output_resolution"])}>
              <option value="original">Original</option>
              <option value="1080p">1080p</option>
              <option value="720p">720p</option>
              <option value="480p">480p</option>
            </select>
          </label>
          <label className="col-span-1 space-y-1">
            <span className="text-muted">Quality</span>
            <select className="field-select" value={value.quality} onChange={(e) => set("quality", e.target.value as Settings["quality"])}>
              <option value="draft">Draft (small file)</option>
              <option value="balanced">Balanced</option>
              <option value="high">High</option>
            </select>
          </label>
          <label className="col-span-1 space-y-1">
            <span className="text-muted">Whisper model</span>
            <select
              className="field-select"
              value={value.whisper_model}
              disabled={analysisLocked}
              onChange={(e) => set("whisper_model", e.target.value)}
            >
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                  {m.startsWith("tiny") ? " (fastest)" : m.startsWith("base") ? " (more accurate)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="col-span-1 space-y-1">
            <span className="text-muted">Language</span>
            <select
              className="field-select"
              value={value.language ?? ""}
              disabled={analysisLocked}
              onChange={(e) => set("language", e.target.value || null)}
            >
              {LANGUAGES.map((l) => (
                <option key={l.label} value={l.code ?? ""}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>
          <label className="col-span-1 space-y-1">
            <span className="text-muted">Max output length</span>
            <input
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              placeholder="No limit"
              className="field-select"
              value={value.max_output_duration ?? ""}
              onChange={(e) => set("max_output_duration", e.target.value === "" ? null : Number(e.target.value))}
              aria-describedby={`${id}-max-help`}
            />
            <span id={`${id}-max-help`} className="block text-xs text-faint">
              Seconds
            </span>
          </label>
          <label className="col-span-1 flex items-center gap-2 self-start pt-6">
            <input
              type="checkbox"
              className="h-4 w-4 accent-[var(--color-keep)]"
              checked={value.keep_audio}
              onChange={(e) => set("keep_audio", e.target.checked)}
            />
            Keep audio
          </label>
          {analysisLocked && (
            <p className="col-span-2 text-xs text-faint">Model and language are fixed for this upload. Start a new edit to change them.</p>
          )}
        </div>
      )}

      {errors.length > 0 && (
        <ul id={`${id}-err`} className="mt-4 space-y-1 text-sm text-danger" role="alert">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}

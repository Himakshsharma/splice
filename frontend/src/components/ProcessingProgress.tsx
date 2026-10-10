import { Check, Loader2, X } from "lucide-react";
import type { Job, JobStatus } from "../types/api";

export const STAGES: { status: JobStatus; label: string }[] = [
  { status: "validating", label: "Validating video" },
  { status: "extracting_audio", label: "Extracting audio" },
  { status: "transcribing", label: "Transcribing speech" },
  { status: "detecting_silence", label: "Detecting silence" },
  { status: "generating_edit_plan", label: "Generating edit decisions" },
  { status: "rendering", label: "Rendering output" },
  { status: "completed", label: "Preparing download" },
];

interface Props {
  phase: "uploading" | "processing";
  uploadProgress: number;
  job: Job | null;
  rerender: boolean;
  connectionError: string | null;
  onCancel: () => void;
  cancelling: boolean;
}

/** Shows only real states reported by the server; percentages appear only when the server measures them. */
export function ProcessingProgress({ phase, uploadProgress, job, rerender, connectionError, onCancel, cancelling }: Props) {
  const status = job?.status ?? "queued";
  const activeIdx = STAGES.findIndex((s) => s.status === status);
  const progress = phase === "uploading" ? uploadProgress : job?.progress ?? null;
  const skipped = rerender ? new Set<JobStatus>(["validating", "extracting_audio", "transcribing"]) : new Set<JobStatus>();
  const heading =
    phase === "uploading" ? "Uploading video" : status === "queued" ? "Waiting for a free worker" : job?.stage_label ?? "Processing";

  return (
    <section className="panel p-5 sm:p-6" aria-live="polite" aria-busy="true">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm text-muted">{rerender ? "Re-rendering with new settings" : "Working on your video"}</p>
          <h2 className="mt-0.5 text-xl font-semibold" data-testid="stage-heading">
            {heading}
          </h2>
        </div>
        <button type="button" className="btn btn-ghost !py-2 text-sm" onClick={onCancel} disabled={cancelling}>
          <X size={15} aria-hidden /> {cancelling ? "Cancelling…" : "Cancel"}
        </button>
      </div>

      <div
        className="relative mt-5 h-2 overflow-hidden rounded-full bg-raised"
        role="progressbar"
        aria-label={heading}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress === null ? undefined : Math.round(progress * 100)}
      >
        {progress === null ? (
          <div className="progress-indeterminate absolute inset-y-0 w-2/5 rounded-full bg-gradient-to-r from-keep/0 via-keep to-cut/0" />
        ) : (
          <div className="h-full rounded-full bg-keep transition-[width] duration-300" style={{ width: `${Math.max(2, progress * 100)}%` }} />
        )}
      </div>
      <p className="tnum mt-2 text-xs text-faint">
        {progress === null ? "This step doesn't report a percentage — it's running." : `${Math.round(progress * 100)}%`}
      </p>

      <ol className="mt-6 grid gap-2 sm:grid-cols-2">
        {STAGES.map((stage, i) => {
          const done = phase === "processing" && (activeIdx > i || status === "completed") && !skipped.has(stage.status);
          const active = phase === "processing" && i === activeIdx;
          const isSkipped = skipped.has(stage.status);
          return (
            <li key={stage.status} className={`flex items-center gap-2.5 text-sm ${active ? "text-text" : done ? "text-muted" : "text-faint"}`}>
              <span
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
                  done ? "border-keep bg-keep text-[#120f22]" : active ? "border-keep" : "border-line"
                }`}
              >
                {done ? <Check size={12} strokeWidth={3} aria-hidden /> : active ? <Loader2 size={12} className="animate-spin text-keep" aria-hidden /> : null}
              </span>
              {stage.label}
              {isSkipped && <span className="text-xs text-faint">(reused)</span>}
            </li>
          );
        })}
      </ol>

      {connectionError && <p className="mt-4 text-sm text-cut">{connectionError}</p>}
    </section>
  );
}

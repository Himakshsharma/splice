import type { ResultInfo } from "../types/api";
import { formatBytes, formatDuration, formatResolution } from "../utils/format";

export function ResultsSummary({ result }: { result: ResultInfo }) {
  const keptPct = 100 - result.removed_percent;
  return (
    <section className="panel p-5 sm:p-6" aria-label="Edit summary">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted">Edited length</p>
          <p className="display tnum mt-1 text-5xl" data-testid="output-duration">
            {formatDuration(result.output_duration)}
          </p>
          <p className="tnum mt-1 text-sm text-muted">
            from {formatDuration(result.original_duration)} — {formatDuration(result.removed_duration)} of silence removed
          </p>
        </div>
        <span className="rounded-full border border-line px-3 py-1 text-xs text-muted">
          {result.render_mode === "preview" ? "Quick preview" : "Final export"} · {formatResolution(result.output_width, result.output_height)} ·{" "}
          {formatBytes(result.output_size_bytes)}
        </span>
      </div>

      {/* proportion bar: kept vs removed */}
      <div className="mt-5 flex h-3 overflow-hidden rounded-full" aria-hidden>
        <div className="bg-keep" style={{ width: `${keptPct}%` }} />
        <div className="hatch flex-1 bg-raised" />
      </div>

      <dl className="tnum mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          ["Removed", `${result.removed_percent.toFixed(1)}%`],
          ["Cuts", String(result.cut_count)],
          ["Segments kept", String(result.retained_count)],
          ["Rendered with", result.render_engine === "moviepy" ? "MoviePy" : "FFmpeg"],
        ].map(([k, v]) => (
          <div key={k}>
            <dt className="text-xs text-muted">{k}</dt>
            <dd className="mt-0.5 text-xl font-semibold">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

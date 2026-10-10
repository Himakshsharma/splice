import type { EditDecision } from "../types/api";
import { formatTimecode, humanizeReason } from "../utils/format";

/** The full edit decision list — the exact data the renderer used. */
export function EditDecisionTable({ decisions, onSeek }: { decisions: EditDecision[]; onSeek: (t: number) => void }) {
  return (
    <div className="max-h-96 overflow-auto rounded-lg border border-line">
      <table className="tnum w-full min-w-[34rem] text-left text-sm">
        <caption className="sr-only">Edit decisions</caption>
        <thead className="sticky top-0 bg-raised text-xs text-muted">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">#</th>
            <th scope="col" className="px-3 py-2 font-medium">Decision</th>
            <th scope="col" className="px-3 py-2 font-medium">Source</th>
            <th scope="col" className="px-3 py-2 font-medium">Length</th>
            <th scope="col" className="px-3 py-2 font-medium">In output</th>
            <th scope="col" className="px-3 py-2 font-medium">Reason</th>
          </tr>
        </thead>
        <tbody>
          {decisions.map((d) => (
            <tr key={d.index} className="border-t border-line/70">
              <td className="px-3 py-1.5 text-faint">{d.index + 1}</td>
              <td className="px-3 py-1.5">
                <span className={`inline-flex items-center gap-1.5 ${d.decision === "retain" ? "text-keep-soft" : "text-muted"}`}>
                  <span className={`h-2 w-2 rounded-full ${d.decision === "retain" ? "bg-keep" : "bg-faint"}`} />
                  {d.decision === "retain" ? "Keep" : "Cut"}
                </span>
              </td>
              <td className="px-3 py-1.5">
                <button type="button" onClick={() => onSeek(d.source_start)} className="underline-offset-2 hover:underline">
                  {formatTimecode(d.source_start, 2)}–{formatTimecode(d.source_end, 2)}
                </button>
              </td>
              <td className="px-3 py-1.5">{d.duration.toFixed(2)}s</td>
              <td className="px-3 py-1.5 text-muted">
                {d.output_start === null ? "—" : `${formatTimecode(d.output_start, 2)}–${formatTimecode(d.output_end ?? 0, 2)}`}
              </td>
              <td className="px-3 py-1.5 text-muted">{humanizeReason(d.reason)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

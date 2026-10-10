import { useMemo, useRef, type KeyboardEvent, type MouseEvent } from "react";
import type { EditPlan } from "../types/api";
import { formatTimecode } from "../utils/format";

interface Props {
  plan: EditPlan;
  currentTime: number;
  onSeek: (t: number) => void;
}

const H = 120;
const DB_MIN = -60;

/**
 * Loudness envelope of the source with the edit decisions drawn on top:
 * violet = kept, hatched = removed, dashed line = the silence threshold.
 * Click or use the arrow keys to move the original video's playhead.
 */
export function EditTimeline({ plan, currentTime, onSeek }: Props) {
  const ref = useRef<SVGSVGElement>(null);
  const W = 1000;
  const dur = plan.source_duration || 1;
  const x = (t: number) => (t / dur) * W;
  const y = (db: number) => {
    const norm = Math.min(1, Math.max(0, (db - DB_MIN) / -DB_MIN));
    return (H / 2) * (1 - norm);
  };

  const path = useMemo(() => {
    const { db, seconds_per_point: step } = plan.waveform;
    if (!db.length) return "";
    const top = db.map((v, i) => `${(i * step / dur) * W},${y(v)}`);
    const bottom = db.map((v, i) => `${(i * step / dur) * W},${H - y(v)}`).reverse();
    return `M0,${H / 2} L${top.join(" L")} L${bottom.join(" L")} Z`;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan]);

  const seekFromEvent = (e: MouseEvent<SVGSVGElement>) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return;
    onSeek(Math.min(dur, Math.max(0, ((e.clientX - box.left) / box.width) * dur)));
  };
  const onKey = (e: KeyboardEvent) => {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (delta) {
      e.preventDefault();
      onSeek(Math.min(dur, Math.max(0, currentTime + delta * (e.shiftKey ? 5 : 1))));
    }
  };

  const thresholdY = y(plan.threshold_db);

  return (
    <div>
      <svg
        ref={ref}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="h-32 w-full cursor-pointer rounded-lg bg-raised"
        onClick={seekFromEvent}
        onKeyDown={onKey}
        tabIndex={0}
        role="slider"
        aria-label="Source timeline. Use arrow keys to seek."
        aria-valuemin={0}
        aria-valuemax={Math.round(dur)}
        aria-valuenow={Math.round(currentTime)}
        aria-valuetext={formatTimecode(currentTime)}
        data-testid="edit-timeline"
      >
        <defs>
          <pattern id="cut-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="8" height="8" fill="var(--color-raised)" />
            <line x1="0" y1="0" x2="0" y2="8" stroke="var(--color-line)" strokeWidth="3" />
          </pattern>
        </defs>
        {plan.decisions.map((d) => (
          <rect
            key={d.index}
            x={x(d.source_start)}
            y={0}
            width={Math.max(0.5, x(d.source_end) - x(d.source_start))}
            height={H}
            fill={d.decision === "remove" ? "url(#cut-hatch)" : "color-mix(in oklab, var(--color-keep) 14%, transparent)"}
          >
            <title>
              {d.decision === "remove" ? "Removed" : "Kept"} {formatTimecode(d.source_start)}–{formatTimecode(d.source_end)}
            </title>
          </rect>
        ))}
        <path d={path} fill="var(--color-keep)" opacity={0.85} />
        {[thresholdY, H - thresholdY].map((ty) => (
          <line key={ty} x1={0} x2={W} y1={ty} y2={ty} stroke="var(--color-cut)" strokeDasharray="6 6" strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={0.7} />
        ))}
        {plan.decisions
          .filter((d) => d.decision === "remove")
          .map((d) => (
            <line key={`c${d.index}`} x1={x(d.source_start)} x2={x(d.source_start)} y1={0} y2={H} stroke="var(--color-cut)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
          ))}
        <line x1={x(currentTime)} x2={x(currentTime)} y1={0} y2={H} stroke="var(--color-text)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="tnum mt-2 flex flex-wrap items-center justify-between gap-3 text-xs text-muted">
        <span>0:00.0</span>
        <span className="flex flex-wrap items-center gap-4">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded-sm bg-keep/60" /> Kept
          </span>
          <span className="flex items-center gap-1.5">
            <span className="hatch h-2.5 w-4 rounded-sm bg-raised" /> Removed
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-4 border-t border-dashed border-cut" /> Threshold {plan.threshold_db} dBFS
          </span>
        </span>
        <span>{formatTimecode(dur)}</span>
      </div>
    </div>
  );
}

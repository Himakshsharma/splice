import type { EditPlan } from "../types/api";

/**
 * Convert a job's real loudness envelope + edit decisions into bars for the 3D view.
 * Each bar is the loudest point in its time bucket; a bar is "kept" if its centre
 * falls inside a retained decision.
 */
export function stripFromPlan(plan: EditPlan, maxBars = 220, dbFloor = -60): { levels: number[]; keep: boolean[] } {
  const { db, seconds_per_point: step } = plan.waveform;
  if (!db.length || plan.source_duration <= 0) return { levels: [], keep: [] };
  const bars = Math.min(maxBars, db.length);
  const per = db.length / bars;
  const levels: number[] = [];
  const keep: boolean[] = [];
  const retained = plan.decisions.filter((d) => d.decision === "retain");
  let r = 0;
  for (let b = 0; b < bars; b++) {
    const from = Math.floor(b * per);
    const to = Math.max(from + 1, Math.floor((b + 1) * per));
    let peak = -Infinity;
    for (let i = from; i < to; i++) peak = Math.max(peak, db[i]);
    const norm = Math.min(1, Math.max(0, (peak - dbFloor) / -dbFloor));
    levels.push(norm ** 1.4);
    const t = ((from + to) / 2) * step;
    while (r < retained.length && retained[r].source_end < t) r++;
    keep.push(r < retained.length && retained[r].source_start <= t && t <= retained[r].source_end);
  }
  return { levels, keep };
}

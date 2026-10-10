/** Display helpers. Pure functions — covered by unit tests. */

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
}

/** 75.4 -> "1:15.4", 3725 -> "1:02:05.0" */
export function formatTimecode(seconds: number, decimals = 1): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const sec = s.toFixed(decimals).padStart(decimals ? 3 + decimals : 2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** Human duration: 4.25 -> "4.3s", 95 -> "1m 35s" */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function formatResolution(w: number | null | undefined, h: number | null | undefined): string {
  return w && h ? `${w}×${h}` : "—";
}

export function humanizeReason(reason: string): string {
  const map: Record<string, string> = {
    speech: "Speech",
    silence: "Silence",
    too_short: "Too short to keep",
    max_duration: "Over max duration",
    no_speech_detected: "No speech found — kept",
  };
  return reason
    .split("+")
    .map((r) => map[r] ?? r.replace(/_/g, " "))
    .join(" + ");
}

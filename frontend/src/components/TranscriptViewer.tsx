import type { Transcript } from "../types/api";
import { formatTimecode } from "../utils/format";

interface Props {
  transcript: Transcript | null;
  currentTime: number;
  onSeek: (t: number) => void;
}

export function TranscriptViewer({ transcript, currentTime, onSeek }: Props) {
  if (!transcript) return <p className="text-sm text-muted">Loading transcript…</p>;
  if (transcript.status !== "completed") {
    const fallback: Record<string, string> = {
      empty: "Whisper did not detect any speech in this video.",
      disabled: "Transcription is turned off on this server. Cuts were made from audio energy only.",
      unavailable: "Whisper could not run on this server. Cuts were made from audio energy only.",
      pending: "The transcript is still being prepared.",
    };
    return <p className="text-sm text-muted">{transcript.message ?? fallback[transcript.status]}</p>;
  }
  return (
    <div>
      <p className="mb-3 text-xs text-faint">
        Whisper {transcript.model} · {transcript.language ? `language: ${transcript.language}` : "language auto-detected"} ·
        timestamps are approximate. Select a line to jump to it in the original.
      </p>
      <ol className="max-h-80 space-y-1 overflow-y-auto pr-1" data-testid="transcript">
        {transcript.segments.map((s, i) => {
          const active = currentTime >= s.start && currentTime < s.end;
          return (
            <li key={i}>
              <button
                type="button"
                onClick={() => onSeek(s.start)}
                className={`flex w-full gap-3 rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
                  active ? "bg-keep/15 text-text" : "text-text/85 hover:bg-raised"
                }`}
              >
                <span className="tnum w-14 shrink-0 text-xs leading-5 text-keep-soft">{formatTimecode(s.start)}</span>
                <span>{s.text}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

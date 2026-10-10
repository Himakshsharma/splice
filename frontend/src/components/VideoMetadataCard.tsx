import { FileVideo, RefreshCw, Trash2 } from "lucide-react";
import type { SourceInfo } from "../types/api";
import { formatBytes, formatDuration, formatResolution } from "../utils/format";
import type { ClientMeta } from "../utils/validation";

interface Props {
  file: File;
  clientMeta: ClientMeta | null;
  serverMeta: SourceInfo | null;
  onReplace: () => void;
  onRemove: () => void;
  locked: boolean;
}

/** Shows browser-read metadata immediately, then the server's FFprobe results once validated. */
export function VideoMetadataCard({ file, clientMeta, serverMeta, onReplace, onRemove, locked }: Props) {
  const rows: [string, string][] = [
    ["Size", formatBytes(file.size)],
    ["Length", formatDuration(serverMeta?.duration ?? clientMeta?.duration ?? NaN)],
    ["Resolution", formatResolution(serverMeta?.width ?? clientMeta?.width, serverMeta?.height ?? clientMeta?.height)],
    ["Frame rate", serverMeta?.fps ? `${serverMeta.fps} fps` : "after upload"],
  ];
  if (serverMeta) rows.push(["Codecs", [serverMeta.video_codec, serverMeta.audio_codec].filter(Boolean).join(" + ") || "—"]);

  return (
    <div className="panel p-4">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-raised">
          <FileVideo size={18} className="text-keep" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold" title={file.name}>
            {file.name}
          </p>
          <p className="text-xs text-muted">{serverMeta ? "Checked by the server" : "Read in your browser"}</p>
        </div>
      </div>
      <dl className="tnum mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2 border-b border-line/60 pb-1.5">
            <dt className="text-muted">{k}</dt>
            <dd className="truncate text-right">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-4 flex gap-2">
        <button type="button" className="btn btn-ghost flex-1 !py-2 text-sm" onClick={onReplace} disabled={locked}>
          <RefreshCw size={15} aria-hidden /> Replace
        </button>
        <button type="button" className="btn btn-ghost flex-1 !py-2 text-sm" onClick={onRemove} disabled={locked}>
          <Trash2 size={15} aria-hidden /> Remove
        </button>
      </div>
    </div>
  );
}

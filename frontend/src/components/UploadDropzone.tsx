import { FileVideo, Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

interface Props {
  onFile: (file: File) => void;
  maxMb: number;
  extensions: string[];
  disabled?: boolean;
}

export function UploadDropzone({ onFile, maxMb, extensions, disabled }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (disabled) return;
    const file = e.dataTransfer.files?.[0];
    if (file) onFile(file);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={handleDrop}
      className={`flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors ${
        over ? "border-keep bg-keep/10" : "border-line hover:border-faint"
      }`}
      data-testid="dropzone"
    >
      <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-raised">
        {over ? <FileVideo className="text-keep" aria-hidden /> : <Upload className="text-keep" aria-hidden />}
      </span>
      <p className="text-lg font-semibold">Drop a video here</p>
      <p className="mt-1 text-sm text-muted">
        {extensions.map((e) => e.slice(1).toUpperCase()).join(", ")} · up to {maxMb} MB
      </p>
      <button type="button" className="btn btn-ghost mt-5" onClick={() => input.current?.click()} disabled={disabled}>
        Browse files
      </button>
      <input
        ref={input}
        type="file"
        accept={[...extensions, "video/*"].join(",")}
        className="sr-only"
        aria-label="Choose a video file"
        data-testid="file-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = ""; // allow choosing the same file again
        }}
      />
    </div>
  );
}

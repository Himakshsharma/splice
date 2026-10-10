import { AlertTriangle, RotateCcw, X } from "lucide-react";

interface Props {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  onDismiss?: () => void;
  tone?: "error" | "warning";
}

export function ErrorBanner({ title, message, onRetry, retryLabel = "Try again", onDismiss, tone = "error" }: Props) {
  const color = tone === "error" ? "border-danger/40 bg-danger/10" : "border-cut/40 bg-cut/10";
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`flex items-start gap-3 rounded-xl border px-4 py-3 ${color}`}>
      <AlertTriangle size={18} className={`mt-0.5 shrink-0 ${tone === "error" ? "text-danger" : "text-cut"}`} aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        {title && <p className="font-semibold">{title}</p>}
        <p className="text-text/85">{message}</p>
        {onRetry && (
          <button type="button" onClick={onRetry} className="mt-2 inline-flex items-center gap-1.5 font-semibold text-keep-soft hover:text-text">
            <RotateCcw size={14} aria-hidden /> {retryLabel}
          </button>
        )}
      </div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} aria-label="Dismiss" className="text-muted hover:text-text">
          <X size={16} />
        </button>
      )}
    </div>
  );
}

import { Download } from "lucide-react";

export function DownloadButton({ href, filename }: { href: string; filename: string }) {
  return (
    <a href={href} download={filename} className="btn btn-primary px-6 py-3 text-base" data-testid="download">
      <Download size={18} aria-hidden /> Download MP4
    </a>
  );
}

import { forwardRef } from "react";

interface Props {
  title: string;
  src: string;
  caption?: string;
  onTime?: (t: number) => void;
}

/** A labelled HTML5 player that keeps the source aspect ratio (letterboxed in a 16:9 frame). */
export const VideoPreview = forwardRef<HTMLVideoElement, Props>(function VideoPreview({ title, src, caption, onTime }, ref) {
  return (
    <figure className="min-w-0">
      <figcaption className="mb-2 flex items-baseline justify-between gap-2 text-sm">
        <span className="font-semibold">{title}</span>
        {caption && <span className="tnum text-xs text-muted">{caption}</span>}
      </figcaption>
      <div className="aspect-video overflow-hidden rounded-xl border border-line bg-black">
        <video
          ref={ref}
          src={src}
          controls
          playsInline
          preload="metadata"
          className="h-full w-full object-contain"
          onTimeUpdate={(e) => onTime?.(e.currentTarget.currentTime)}
          aria-label={title}
        />
      </div>
    </figure>
  );
});

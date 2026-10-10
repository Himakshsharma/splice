export interface FileCheck {
  ok: boolean;
  message?: string;
}

export const DEFAULT_EXTENSIONS = [".mp4", ".mov", ".webm", ".m4v", ".mkv"];

/** Fast checks before uploading. The server re-validates the actual media with FFprobe. */
export function checkFile(file: File, maxMb: number, extensions: string[] = DEFAULT_EXTENSIONS): FileCheck {
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (!extensions.includes(ext)) {
    return {
      ok: false,
      message: `“${file.name}” isn't a supported video. Use ${extensions.map((e) => e.slice(1).toUpperCase()).join(", ")}.`,
    };
  }
  if (file.size === 0) return { ok: false, message: "This file is empty." };
  if (file.size > maxMb * 1024 * 1024) {
    return { ok: false, message: `This file is ${(file.size / 1048576).toFixed(1)} MB. The limit here is ${maxMb} MB.` };
  }
  return { ok: true };
}

export interface ClientMeta {
  duration: number;
  width: number;
  height: number;
}

/** Read duration/resolution in the browser so the user sees metadata before uploading. */
export function readVideoMetadata(url: string, timeoutMs = 8000): Promise<ClientMeta | null> {
  return new Promise((resolve) => {
    const video = document.createElement("video");
    const done = (meta: ClientMeta | null) => {
      clearTimeout(timer);
      video.removeAttribute("src");
      video.load();
      resolve(meta);
    };
    const timer = setTimeout(() => done(null), timeoutMs);
    video.preload = "metadata";
    video.muted = true;
    video.onloadedmetadata = () =>
      done(
        Number.isFinite(video.duration)
          ? { duration: video.duration, width: video.videoWidth, height: video.videoHeight }
          : null,
      );
    video.onerror = () => done(null);
    video.src = url;
  });
}

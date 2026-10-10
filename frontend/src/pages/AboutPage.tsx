import { REPO_URL } from "../components/Footer";
import { Link } from "../router";
import { API_BASE } from "../services/api";

const PIPELINE: [string, string][] = [
  ["Validate", "FFprobe reads the container, streams, duration, resolution and frame rate. Files without video or without audio are rejected with a clear reason."],
  ["Extract audio", "FFmpeg decodes the first audio track once into 16 kHz mono PCM — the format Whisper expects, reused by the silence detector."],
  ["Transcribe", "Whisper (tiny or base, on the CPU) produces timestamped segments and word timings. No API key or external service is involved."],
  ["Detect silence", "NumPy slices the waveform into 30 ms frames every 10 ms, computes RMS energy and converts it to dBFS. Runs of frames below your threshold and longer than your minimum pause become silence intervals."],
  ["Plan the edit", "Each silence is shrunk by the padding you chose. Words Whisper heard are protected, cuts too small to notice are skipped, and stray fragments between cuts are dropped. The result is a validated edit decision list."],
  ["Render", "MoviePy cuts and joins the kept segments (or a single FFmpeg trim/concat pass for long videos) and encodes H.264 + AAC. FFprobe verifies the file before it is offered for download."],
];

export function AboutPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-14 sm:px-6">
      <h1 className="display text-4xl sm:text-6xl">How SPLICE works</h1>
      <p className="mt-6 max-w-2xl text-lg leading-relaxed text-muted">
        SPLICE is a portfolio project that automates the most tedious part of editing talking videos: removing the pauses. It
        pairs a speech-recognition model with classic signal processing, and shows every decision it makes so you can check
        and adjust it.
      </p>

      <h2 className="mt-14 text-2xl font-semibold">The pipeline</h2>
      <ol className="mt-6 space-y-6">
        {PIPELINE.map(([title, body], i) => (
          <li key={title} className="grid gap-1 border-l-2 border-line pl-5 sm:grid-cols-[10rem_1fr] sm:gap-6">
            <p className="font-semibold">
              <span className="tnum mr-2 text-keep-soft">{i + 1}.</span>
              {title}
            </p>
            <p className="leading-relaxed text-muted">{body}</p>
          </li>
        ))}
      </ol>

      <h2 className="mt-14 text-2xl font-semibold">Why not let Whisper decide the cuts?</h2>
      <p className="mt-4 leading-relaxed text-muted">
        Whisper is a transcription model. Its timestamps are approximate — often off by a tenth of a second or more — and a
        gap between two transcript segments isn't necessarily silence. Cutting on those gaps alone clips words and breaks the
        rhythm of sentences. SPLICE measures the silence directly from the audio, and uses Whisper only to make sure nothing
        that was actually said gets cut.
      </p>

      <h2 className="mt-14 text-2xl font-semibold">Limits of this free demo</h2>
      <ul className="mt-4 list-disc space-y-2 pl-5 leading-relaxed text-muted">
        <li>It runs on a shared CPU, so a one-minute clip can take a minute or more to process. Uploads are capped in size and length.</li>
        <li>The free server sleeps when unused; the first request after a pause can take a while.</li>
        <li>Storage is temporary. Files are deleted when a job expires, and a server restart clears everything, including running jobs.</li>
        <li>Energy-based detection can mistake background music or constant noise for speech — raise the threshold for noisy recordings.</li>
        <li>Download links are secret, expiring capability links rather than user accounts.</li>
      </ul>

      <div className="mt-14 flex flex-wrap gap-3">
        <Link href="/editor" className="btn btn-primary">
          Try it on a video
        </Link>
        <a href={`${API_BASE}/api/docs`} className="btn btn-ghost">
          Interactive API docs
        </a>
        {REPO_URL && (
          <a href={REPO_URL} className="btn btn-ghost" target="_blank" rel="noreferrer">
            Source code
          </a>
        )}
      </div>
    </div>
  );
}

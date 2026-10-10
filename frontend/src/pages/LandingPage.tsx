import { AudioWaveform, Captions, Download, Scissors, ShieldCheck } from "lucide-react";
import { useMemo } from "react";
import { CutScene3D, demoStrip } from "../components/CutScene3D";
import { Link } from "../router";

export function HeroSection() {
  const strip = useMemo(() => demoStrip(), []);
  return (
    <section className="relative overflow-hidden">
      <div className="mx-auto max-w-7xl px-4 pt-14 sm:px-6 sm:pt-20">
        <h1 className="display max-w-5xl text-[clamp(2.6rem,7.4vw,6.4rem)]">Your videos. Less silence. More impact.</h1>
        <div className="mt-8 flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <p className="max-w-xl text-lg leading-relaxed text-muted">
            SPLICE listens to your recording, finds the dead air between sentences and cuts it out for you. Whisper
            transcribes what was said, an audio-energy detector finds the pauses, and you download a tighter MP4.
          </p>
          <div className="flex shrink-0 flex-wrap gap-3">
            <Link href="/editor" className="btn btn-primary px-6 py-3.5 text-base">
              <Scissors size={18} aria-hidden /> Start editing
            </Link>
            <Link href="/#how-it-works" className="btn btn-ghost px-5 py-3.5 text-base">
              See how it works
            </Link>
          </div>
        </div>
      </div>

      <figure className="relative mt-10">
        <CutScene3D
          mode="loop"
          levels={strip.levels}
          keep={strip.keep}
          className="h-[300px] w-full sm:h-[380px]"
          label="Animation: a playhead sweeps an audio waveform, silent sections collapse and the remaining speech slides together."
        />
        <figcaption className="mx-auto max-w-7xl px-4 pb-4 text-sm text-faint sm:px-6">
          The blue playhead finds the pauses. Grey sections are cut, and the speech closes up into one continuous take.
        </figcaption>
      </figure>
    </section>
  );
}

const STEPS = [
  {
    title: "Drop in a video",
    body: "MP4, MOV or WebM. SPLICE checks the file with FFprobe and shows its length, resolution and frame rate.",
  },
  {
    title: "Choose how tight to cut",
    body: "Set the silence threshold, the shortest pause worth cutting and how much breathing room to keep around words.",
  },
  {
    title: "Review and download",
    body: "Compare original and edit side by side, inspect every cut on the timeline, then download the MP4.",
  },
];

const FEATURES = [
  {
    icon: Captions,
    title: "Whisper transcription",
    body: "OpenAI's open-source Whisper model runs on the server — no API key — and returns timestamped text. Words it hears are protected from being cut, even when they are spoken quietly.",
  },
  {
    icon: AudioWaveform,
    title: "Silence detection",
    body: "The audio is split into 30 ms frames, measured in dBFS with NumPy, and runs of quiet frames longer than your minimum pause become cut candidates.",
  },
  {
    icon: Scissors,
    title: "Automatic jump cuts",
    body: "An edit-decision engine adds padding, skips micro-cuts and drops stray noises, producing one validated cut list that drives both the render and the timeline you see.",
  },
  {
    icon: Download,
    title: "Clean MP4 export",
    body: "MoviePy and FFmpeg re-encode the kept segments to H.264 + AAC, frame-accurate, at the original resolution or a smaller preset. Every file is checked with FFprobe before you can download it.",
  },
];

const STACK: [string, string][] = [
  ["OpenAI Whisper", "Speech-to-text with word timestamps"],
  ["NumPy", "Frame energy, dBFS and silence intervals"],
  ["FFmpeg / FFprobe", "Probing, audio extraction, encoding"],
  ["MoviePy", "Sub-clipping and concatenating segments"],
  ["FastAPI", "Upload, job and download API"],
  ["React + TypeScript", "This interface"],
  ["Three.js", "The 3D cut visualisations"],
  ["SQLite", "Short-lived job metadata"],
];

export function LandingPage() {
  return (
    <>
      <HeroSection />

      <section id="how-it-works" className="scroll-mt-20 border-t border-line">
        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6">
          <h2 className="display text-4xl sm:text-5xl">Three steps, one cleaner take</h2>
          <ol className="mt-12 grid gap-10 md:grid-cols-3">
            {STEPS.map((s, i) => (
              <li key={s.title} className="relative pl-14">
                <span className="wide tnum absolute left-0 top-0 flex h-10 w-10 items-center justify-center rounded-full border border-keep/50 text-lg font-semibold text-keep-soft">
                  {i + 1}
                </span>
                <h3 className="text-xl font-semibold">{s.title}</h3>
                <p className="mt-2 leading-relaxed text-muted">{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="features" className="scroll-mt-20 border-t border-line bg-panel/40">
        <div className="mx-auto grid max-w-7xl gap-12 px-4 py-20 sm:px-6 lg:grid-cols-[1fr_1.6fr]">
          <div>
            <h2 className="display text-4xl sm:text-5xl">What happens to your video</h2>
            <p className="mt-5 max-w-md leading-relaxed text-muted">
              Whisper is used for what it is good at — understanding speech. Deciding where the silence is stays with a
              transparent signal-processing step you can tune and inspect.
            </p>
          </div>
          <dl className="divide-y divide-line border-y border-line">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <div key={title} className="grid gap-3 py-7 sm:grid-cols-[14rem_1fr]">
                <dt className="flex items-center gap-3 font-semibold">
                  <Icon size={20} className="text-keep" aria-hidden /> {title}
                </dt>
                <dd className="leading-relaxed text-muted">{body}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section className="border-t border-line">
        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6">
          <h2 className="display text-3xl sm:text-4xl">Built with</h2>
          <ul className="mt-10 grid gap-x-10 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">
            {STACK.map(([name, role]) => (
              <li key={name} className="border-l-2 border-keep/60 pl-4">
                <p className="font-semibold">{name}</p>
                <p className="text-sm text-muted">{role}</p>
              </li>
            ))}
          </ul>

          <div className="mt-16 flex items-start gap-4 rounded-2xl border border-line p-6">
            <ShieldCheck className="mt-0.5 shrink-0 text-ok" aria-hidden />
            <div className="text-sm leading-relaxed text-muted">
              <p className="font-semibold text-text">Your video is processed on the SPLICE server, not shared.</p>
              <p className="mt-1">
                Uploads are stored in a private temporary folder, reachable only with a secret link issued to your browser,
                and deleted automatically when the job expires — or immediately when you press Delete. This is a free demo
                running on a CPU, so uploads are limited in size and length.
              </p>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}

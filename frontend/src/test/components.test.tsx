import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EditingSettings } from "../components/EditingSettings";
import { ErrorBanner } from "../components/ErrorBanner";
import { ProcessingProgress } from "../components/ProcessingProgress";
import { ResultsSummary } from "../components/ResultsSummary";
import { UploadDropzone } from "../components/UploadDropzone";
import { LandingPage } from "../pages/LandingPage";
import type { Job, ResultInfo } from "../types/api";
import { DEFAULT_SETTINGS } from "../utils/settings";

// jsdom has no WebGL or observers; the 3D component falls back to a flat chart.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const job = (over: Partial<Job>): Job => ({
  job_id: "a".repeat(32),
  status: "transcribing",
  stage_label: "Transcribing speech",
  progress: null,
  created_at: "",
  updated_at: "",
  expires_at: "",
  error: null,
  source: null,
  settings: DEFAULT_SETTINGS,
  result: null,
  ...over,
});

describe("LandingPage", () => {
  it("renders the hero, workflow and features", () => {
    render(<LandingPage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Your videos. Less silence. More impact.");
    expect(screen.getAllByRole("link", { name: /start editing/i }).length).toBeGreaterThan(0);
    expect(screen.getByText("Whisper transcription")).toBeInTheDocument();
    expect(screen.getByText("Drop in a video")).toBeInTheDocument();
  });
});

describe("UploadDropzone", () => {
  it("passes the chosen file up", () => {
    const onFile = vi.fn();
    render(<UploadDropzone onFile={onFile} maxMb={50} extensions={[".mp4"]} />);
    const f = new File(["x"], "clip.mp4", { type: "video/mp4" });
    fireEvent.change(screen.getByTestId("file-input"), { target: { files: [f] } });
    expect(onFile).toHaveBeenCalledWith(f);
  });
});

describe("EditingSettings", () => {
  it("emits changed values and shows validation errors", () => {
    const onChange = vi.fn();
    render(<EditingSettings value={DEFAULT_SETTINGS} onChange={onChange} models={["tiny", "base"]} errors={["Bad padding"]} />);
    fireEvent.change(screen.getByLabelText("Silence threshold"), { target: { value: "-30" } });
    expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_SETTINGS, silence_threshold_db: -30 });
    fireEvent.click(screen.getByRole("radio", { name: "Quick preview" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_SETTINGS, mode: "preview" });
    expect(screen.getByRole("alert")).toHaveTextContent("Bad padding");
  });
});

describe("ProcessingProgress", () => {
  it("shows the real stage and an indeterminate bar when there is no percentage", () => {
    render(<ProcessingProgress phase="processing" uploadProgress={1} job={job({})} rerender={false} connectionError={null} onCancel={() => {}} cancelling={false} />);
    expect(screen.getByTestId("stage-heading")).toHaveTextContent("Transcribing speech");
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  });
  it("shows a measured percentage while rendering", () => {
    render(<ProcessingProgress phase="processing" uploadProgress={1} job={job({ status: "rendering", stage_label: "Rendering output", progress: 0.42 })} rerender={false} connectionError="Connection to the server was lost. Retrying…" onCancel={() => {}} cancelling={false} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
    expect(screen.getByText(/Retrying/)).toBeInTheDocument();
  });
});

describe("ResultsSummary and errors", () => {
  it("summarises the real result", () => {
    const result: ResultInfo = {
      original_duration: 60, output_duration: 45, removed_duration: 15, removed_percent: 25, cut_count: 6, retained_count: 7,
      render_mode: "final", render_engine: "moviepy", output_width: 1280, output_height: 720, output_size_bytes: 4_000_000,
      transcript_status: "completed", transcript_language: "en", warnings: [],
    };
    render(<ResultsSummary result={result} />);
    expect(screen.getByTestId("output-duration")).toHaveTextContent("45.0s");
    expect(screen.getByText("25.0%")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
  });
  it("error banner offers a retry", () => {
    const retry = vi.fn();
    render(<ErrorBanner message="FFmpeg could not process this video." onRetry={retry} />);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(retry).toHaveBeenCalled();
  });
});

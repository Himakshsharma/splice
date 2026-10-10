/** Types mirroring backend/app/schemas/jobs.py. Keep the two in sync. */

export type JobStatus =
  | "queued"
  | "validating"
  | "extracting_audio"
  | "transcribing"
  | "detecting_silence"
  | "generating_edit_plan"
  | "rendering"
  | "completed"
  | "failed"
  | "cancelled"
  | "expired";

export const TERMINAL_STATUSES: readonly JobStatus[] = ["completed", "failed", "cancelled", "expired"];

export interface EditSettings {
  silence_threshold_db: number;
  min_silence_duration: number;
  padding_before: number;
  padding_after: number;
  min_segment_duration: number;
  max_output_duration: number | null;
  whisper_model: string;
  language: string | null;
  protect_speech: boolean;
  output_resolution: "original" | "1080p" | "720p" | "480p";
  quality: "draft" | "balanced" | "high";
  keep_audio: boolean;
  mode: "preview" | "final";
}

export interface ErrorInfo {
  code: string;
  message: string;
}

export interface SourceInfo {
  filename: string;
  size_bytes: number;
  duration: number;
  width: number | null;
  height: number | null;
  fps: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  has_audio: boolean;
  container: string | null;
}

export interface ResultInfo {
  original_duration: number;
  output_duration: number;
  removed_duration: number;
  removed_percent: number;
  cut_count: number;
  retained_count: number;
  render_mode: "preview" | "final";
  render_engine: string;
  output_width: number | null;
  output_height: number | null;
  output_size_bytes: number;
  transcript_status: string;
  transcript_language: string | null;
  warnings: string[];
}

export interface Job {
  job_id: string;
  status: JobStatus;
  stage_label: string;
  progress: number | null;
  created_at: string;
  updated_at: string;
  expires_at: string;
  error: ErrorInfo | null;
  source: SourceInfo | null;
  settings: EditSettings;
  result: ResultInfo | null;
}

export interface CreateJobResponse {
  job_id: string;
  access_token: string;
  job: Job;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

export interface Transcript {
  status: "pending" | "completed" | "empty" | "unavailable" | "disabled";
  engine: string | null;
  model: string | null;
  language: string | null;
  message: string | null;
  segments: TranscriptSegment[];
}

export interface EditDecision {
  index: number;
  decision: "retain" | "remove";
  reason: string;
  source_start: number;
  source_end: number;
  duration: number;
  output_start: number | null;
  output_end: number | null;
}

export interface EditPlan {
  source_duration: number;
  output_duration: number;
  removed_duration: number;
  cut_count: number;
  retained_count: number;
  threshold_db: number;
  decisions: EditDecision[];
  silences: { start: number; end: number }[];
  waveform: { seconds_per_point: number; db: number[] };
  warnings: string[];
}

export interface PublicConfig {
  max_upload_mb: number;
  max_video_duration_seconds: number;
  accepted_extensions: string[];
  whisper_engine: string;
  whisper_models: string[];
  default_whisper_model: string;
  job_ttl_minutes: number;
  source_repo_url: string | null;
  defaults: EditSettings;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

/**
 * Typed client for the SPLICE API. All network calls in the UI go through here.
 */
import type {
  ApiErrorBody,
  CreateJobResponse,
  EditPlan,
  EditSettings,
  Job,
  PublicConfig,
  Transcript,
} from "../types/api";

export const API_BASE = ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** True when the request never reached the server (offline, DNS, CORS, server asleep). */
  get isNetwork(): boolean {
    return this.status === 0;
  }
}

export interface JobAuth {
  jobId: string;
  token: string;
}

function toApiError(status: number, body: unknown): ApiError {
  const err = (body as ApiErrorBody | undefined)?.error;
  if (err?.message) return new ApiError(status, err.code, err.message, err.details);
  return new ApiError(status, "http_error", `The server responded with status ${status}.`);
}

async function request<T>(path: string, init: RequestInit = {}, auth?: JobAuth): Promise<T> {
  const headers = new Headers(init.headers);
  if (auth) headers.set("X-Job-Token", auth.token);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the SPLICE server. Check your connection.");
  }
  if (res.status === 204 || res.status === 202) return undefined as T;
  const body = await res.json().catch(() => undefined);
  if (!res.ok) throw toApiError(res.status, body);
  return body as T;
}

export const api = {
  config: () => request<PublicConfig>("/api/config"),

  getJob: (auth: JobAuth, signal?: AbortSignal) => request<Job>(`/api/jobs/${auth.jobId}`, { signal }, auth),

  transcript: (auth: JobAuth) => request<Transcript>(`/api/jobs/${auth.jobId}/transcript`, {}, auth),

  editPlan: (auth: JobAuth) => request<EditPlan>(`/api/jobs/${auth.jobId}/edit-plan`, {}, auth),

  rerender: (auth: JobAuth, settings: EditSettings) =>
    request<Job>(
      `/api/jobs/${auth.jobId}/render`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ settings }) },
      auth,
    ),

  deleteJob: (auth: JobAuth) => request<void>(`/api/jobs/${auth.jobId}`, { method: "DELETE" }, auth),

  /** Media URLs carry the token as a query parameter because <video> and <a> cannot send headers. */
  downloadUrl: (auth: JobAuth, opts: { inline?: boolean; version?: string } = {}) => {
    const q = new URLSearchParams({ token: auth.token });
    if (opts.inline) q.set("inline", "1");
    if (opts.version) q.set("v", opts.version);
    return `${API_BASE}/api/jobs/${auth.jobId}/download?${q.toString()}`;
  },

  /**
   * Upload a video and create a job. Uses XMLHttpRequest because fetch() cannot
   * report upload progress. Returns an abort function alongside the promise.
   */
  createJob(
    file: File,
    settings: EditSettings,
    onProgress?: (fraction: number) => void,
  ): { promise: Promise<CreateJobResponse>; abort: () => void } {
    const xhr = new XMLHttpRequest();
    const promise = new Promise<CreateJobResponse>((resolve, reject) => {
      const form = new FormData();
      form.append("file", file, file.name);
      form.append("settings", JSON.stringify(settings));
      xhr.open("POST", `${API_BASE}/api/jobs`);
      xhr.responseType = "json";
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as CreateJobResponse);
        else reject(toApiError(xhr.status, xhr.response));
      };
      xhr.onerror = () =>
        reject(new ApiError(0, "network_error", "The upload failed. Check your connection and try again."));
      xhr.onabort = () => reject(new ApiError(0, "aborted", "Upload cancelled."));
      xhr.send(form);
    });
    return { promise, abort: () => xhr.abort() };
  },
};

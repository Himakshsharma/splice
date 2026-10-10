import { Box, ChevronDown, Film, RotateCcw, Sparkles, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CutScene3D } from "../components/CutScene3D";
import { DownloadButton } from "../components/DownloadButton";
import { EditDecisionTable } from "../components/EditDecisionTable";
import { EditingSettings } from "../components/EditingSettings";
import { EditTimeline } from "../components/EditTimeline";
import { ErrorBanner } from "../components/ErrorBanner";
import { ProcessingProgress } from "../components/ProcessingProgress";
import { ResultsSummary } from "../components/ResultsSummary";
import { TranscriptViewer } from "../components/TranscriptViewer";
import { UploadDropzone } from "../components/UploadDropzone";
import { VideoMetadataCard } from "../components/VideoMetadataCard";
import { VideoPreview } from "../components/VideoPreview";
import { useJobPolling } from "../hooks/useJobPolling";
import { useObjectUrl } from "../hooks/useObjectUrl";
import { useServerConfig } from "../hooks/useServerConfig";
import { api, ApiError, type JobAuth } from "../services/api";
import type { EditPlan, EditSettings as Settings, Job, Transcript } from "../types/api";
import { formatDuration } from "../utils/format";
import { canRerenderWith, DEFAULT_SETTINGS, validateSettings } from "../utils/settings";
import { stripFromPlan } from "../utils/strip";
import { checkFile, DEFAULT_EXTENSIONS, readVideoMetadata, type ClientMeta } from "../utils/validation";

const ACTIVE = new Set(["queued", "validating", "extracting_audio", "transcribing", "detecting_silence", "generating_edit_plan", "rendering"]);

export function EditorPage() {
  const cfg = useServerConfig();
  const maxMb = cfg.config?.max_upload_mb ?? 50;
  const extensions = cfg.config?.accepted_extensions ?? DEFAULT_EXTENSIONS;
  const models = cfg.config?.whisper_models ?? ["tiny"];

  const [file, setFile] = useState<File | null>(null);
  const fileUrl = useObjectUrl(file);
  const [clientMeta, setClientMeta] = useState<ClientMeta | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const touched = useRef(false);
  useEffect(() => {
    if (cfg.config && !touched.current) setSettings(cfg.config.defaults);
  }, [cfg.config]);

  const [auth, setAuth] = useState<JobAuth | null>(null);
  const [seedJob, setSeedJob] = useState<Job | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isRerender, setIsRerender] = useState(false);
  const [kick, setKick] = useState(0);
  const [cancelling, setCancelling] = useState(false);
  const busyRef = useRef(false);
  const abortUpload = useRef<(() => void) | null>(null);

  const { job, connectionError, fatalError } = useJobPolling(auth, seedJob, kick);
  const status = job?.status;
  const processing = !!status && ACTIVE.has(status);

  // ---- file selection ------------------------------------------------------------------
  const replaceInput = useRef<HTMLInputElement>(null);
  const chooseFile = (f: File) => {
    const check = checkFile(f, maxMb, extensions);
    if (!check.ok) {
      setFileError(check.message ?? "This file can't be used.");
      return;
    }
    setFileError(null);
    setSubmitError(null);
    setClientMeta(null);
    setAuth(null);
    setSeedJob(null);
    setFile(f);
  };
  useEffect(() => {
    if (!fileUrl) return;
    let alive = true;
    readVideoMetadata(fileUrl).then((m) => alive && setClientMeta(m));
    return () => {
      alive = false;
    };
  }, [fileUrl]);

  const removeFile = () => {
    setFile(null);
    setClientMeta(null);
    setAuth(null);
    setSeedJob(null);
    setSubmitError(null);
  };

  // ---- submit / re-render / cancel ---------------------------------------------------------
  const errors = validateSettings(settings);
  const tooLong =
    clientMeta && cfg.config && clientMeta.duration > cfg.config.max_video_duration_seconds
      ? `This video is ${formatDuration(clientMeta.duration)} long. The limit here is ${formatDuration(cfg.config.max_video_duration_seconds)}.`
      : null;

  const startJob = useCallback(async () => {
    if (!file || busyRef.current) return; // guard against double clicks
    busyRef.current = true;
    setSubmitError(null);
    setIsRerender(false);
    setUploading(true);
    setUploadProgress(0);
    setAuth(null);
    setSeedJob(null);
    const { promise, abort } = api.createJob(file, settings, setUploadProgress);
    abortUpload.current = abort;
    try {
      const created = await promise;
      setSeedJob(created.job);
      setAuth({ jobId: created.job_id, token: created.access_token });
    } catch (e) {
      const err = e as ApiError;
      if (err.code !== "aborted") setSubmitError(err.message);
    } finally {
      abortUpload.current = null;
      setUploading(false);
      busyRef.current = false;
    }
  }, [file, settings]);

  const rerender = async () => {
    if (!auth || busyRef.current) return;
    busyRef.current = true;
    setSubmitError(null);
    try {
      const updated = await api.rerender(auth, settings);
      setIsRerender(true);
      setSeedJob(updated);
      setPlan(null);
      setTranscript(null);
      setKick((k) => k + 1);
    } catch (e) {
      setSubmitError((e as ApiError).message);
    } finally {
      busyRef.current = false;
    }
  };

  const cancel = async () => {
    if (uploading) {
      abortUpload.current?.();
      return;
    }
    if (!auth) return;
    setCancelling(true);
    try {
      await api.deleteJob(auth);
    } catch (e) {
      setSubmitError((e as ApiError).message);
    } finally {
      setCancelling(false);
    }
  };

  const deleteFromServer = async () => {
    if (!auth) return;
    try {
      await api.deleteJob(auth);
      setAuth(null);
      setSeedJob(null);
      setPlan(null);
      setTranscript(null);
    } catch (e) {
      setSubmitError((e as ApiError).message);
    }
  };

  // ---- results ----------------------------------------------------------------------------
  const [plan, setPlan] = useState<EditPlan | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [resultsError, setResultsError] = useState<string | null>(null);
  useEffect(() => {
    if (!auth || status !== "completed") return;
    let alive = true;
    setResultsError(null);
    Promise.all([api.editPlan(auth), api.transcript(auth)])
      .then(([p, t]) => {
        if (!alive) return;
        setPlan(p);
        setTranscript(t);
      })
      .catch((e: Error) => alive && setResultsError(e.message));
    return () => {
      alive = false;
    };
  }, [auth, status, job?.updated_at]);

  const originalRef = useRef<HTMLVideoElement>(null);
  const [originalTime, setOriginalTime] = useState(0);
  const seekOriginal = (t: number) => {
    if (originalRef.current) {
      originalRef.current.currentTime = t;
      setOriginalTime(t);
    }
  };
  const strip = useMemo(() => (plan ? stripFromPlan(plan) : null), [plan]);
  const [show3dEdited, setShow3dEdited] = useState(false);

  // ---- derived UI state ---------------------------------------------------------------------
  const completed = status === "completed" && job?.result;
  const settingsChanged = job ? JSON.stringify(job.settings) !== JSON.stringify(settings) : true;
  const rerenderable = !!completed && job && canRerenderWith(job.settings, settings);
  const failedMessage =
    job?.status === "failed" || job?.status === "cancelled" || job?.status === "expired"
      ? job.error?.message ?? (job.status === "expired" ? "This job expired and its files were deleted." : "Processing stopped.")
      : null;

  let primaryLabel = "Remove silence";
  let primaryAction: () => void = startJob;
  if (completed && rerenderable) {
    primaryLabel = settingsChanged ? "Re-render with these settings" : "Settings unchanged";
    primaryAction = rerender;
  } else if (completed) {
    primaryLabel = "Start a new edit";
  }
  const primaryDisabled =
    cfg.status !== "ready" || !file || uploading || processing || errors.length > 0 || !!tooLong || (!!completed && !!rerenderable && !settingsChanged);

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="display text-4xl sm:text-5xl">Editor</h1>
          <p className="mt-2 text-muted">Upload a talking video, tune the cut, review every decision, download.</p>
        </div>
        {cfg.config && (
          <p className="tnum text-xs text-faint">
            Limits on this server: {cfg.config.max_upload_mb} MB, {formatDuration(cfg.config.max_video_duration_seconds)} per video. Files
            are deleted after {cfg.config.job_ttl_minutes} minutes.
          </p>
        )}
      </div>

      {cfg.status === "waking" && (
        <div className="mb-6">
          <ErrorBanner tone="warning" title="Connecting to the server" message={cfg.error} />
        </div>
      )}
      {cfg.status === "error" && (
        <div className="mb-6">
          <ErrorBanner
            title="Can't reach the SPLICE server"
            message={`${cfg.error} Free servers sleep when idle and can take a minute to wake up.`}
            onRetry={cfg.retry}
          />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
        {/* ---------- sidebar ---------- */}
        <aside className="space-y-4">
          {file ? (
            <VideoMetadataCard
              file={file}
              clientMeta={clientMeta}
              serverMeta={job?.source ?? null}
              locked={uploading || processing}
              onReplace={() => replaceInput.current?.click()}
              onRemove={removeFile}
            />
          ) : (
            <div className="panel p-4 text-sm text-muted">No video selected yet.</div>
          )}
          <input
            ref={replaceInput}
            type="file"
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            accept={[...extensions, "video/*"].join(",")}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) chooseFile(f);
              e.target.value = "";
            }}
          />
          {fileError && <ErrorBanner message={fileError} onDismiss={() => setFileError(null)} />}
          {tooLong && <ErrorBanner message={tooLong} />}

          <EditingSettings
            value={settings}
            onChange={(s) => {
              touched.current = true;
              setSettings(s);
            }}
            models={models}
            disabled={uploading || processing}
            analysisLocked={!!completed}
            errors={errors}
          />

          <button
            type="button"
            className="btn btn-primary w-full py-3.5 text-base"
            onClick={primaryAction}
            disabled={primaryDisabled}
            data-testid="primary-action"
          >
            <Sparkles size={18} aria-hidden /> {primaryLabel}
          </button>
          {completed && (
            <button type="button" className="btn btn-ghost w-full" onClick={startJob} disabled={uploading || processing || errors.length > 0}>
              <RotateCcw size={16} aria-hidden /> Re-analyse from scratch
            </button>
          )}
        </aside>

        {/* ---------- main ---------- */}
        <main className="min-w-0 space-y-6" id="editor-main">
          {submitError && <ErrorBanner title="That didn't work" message={submitError} onDismiss={() => setSubmitError(null)} />}
          {fatalError && <ErrorBanner title="Job unavailable" message={fatalError.message} onRetry={file ? startJob : undefined} retryLabel="Upload again" />}

          {!file && <UploadDropzone onFile={chooseFile} maxMb={maxMb} extensions={extensions} />}

          {file && !auth && !uploading && !submitError && (
            <div className="panel flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
              <Film className="text-keep" aria-hidden />
              <p className="text-lg font-semibold">Ready when you are</p>
              <p className="max-w-md text-sm text-muted">
                Adjust the cut settings if you like, then press <span className="text-text">Remove silence</span>. The defaults work well
                for most talking-head recordings.
              </p>
            </div>
          )}

          {(uploading || processing) && (
            <ProcessingProgress
              phase={uploading ? "uploading" : "processing"}
              uploadProgress={uploadProgress}
              job={job}
              rerender={isRerender}
              connectionError={connectionError}
              onCancel={cancel}
              cancelling={cancelling}
            />
          )}

          {failedMessage && !processing && (
            <ErrorBanner
              title={job?.status === "cancelled" ? "Cancelled" : job?.status === "expired" ? "Expired" : "Processing failed"}
              message={failedMessage}
              onRetry={file ? startJob : undefined}
              retryLabel={job?.status === "cancelled" ? "Start again" : "Try again"}
            />
          )}

          {completed && job.result && auth && (
            <div className="space-y-6" data-testid="results">
              <ResultsSummary result={job.result} />

              {job.result.warnings.map((w) => (
                <ErrorBanner key={w} tone="warning" message={w} />
              ))}

              <div className="flex flex-wrap items-center gap-3">
                <DownloadButton
                  href={api.downloadUrl(auth, { version: job.updated_at })}
                  filename={`${(file?.name ?? "video").replace(/\.[^.]+$/, "")}-splice.mp4`}
                />
                <button type="button" className="btn btn-ghost" onClick={deleteFromServer}>
                  <Trash2 size={16} aria-hidden /> Delete from server
                </button>
                <p className="text-xs text-faint">Available until {new Date(job.expires_at).toLocaleTimeString()}.</p>
              </div>

              <div className="grid gap-5 md:grid-cols-2">
                {fileUrl && (
                  <VideoPreview ref={originalRef} title="Original" src={fileUrl} caption={formatDuration(job.result.original_duration)} onTime={setOriginalTime} />
                )}
                <VideoPreview
                  title="Edited"
                  src={api.downloadUrl(auth, { inline: true, version: job.updated_at })}
                  caption={formatDuration(job.result.output_duration)}
                />
              </div>

              {resultsError && <ErrorBanner message={resultsError} />}

              {plan && (
                <section className="panel p-5 sm:p-6">
                  <h2 className="text-lg font-semibold">Timeline</h2>
                  <p className="mb-4 mt-1 text-sm text-muted">The original's loudness with every cut marked. Click to jump the original player there.</p>
                  <EditTimeline plan={plan} currentTime={originalTime} onSeek={seekOriginal} />
                </section>
              )}

              {strip && strip.levels.length > 0 && (
                <section className="panel overflow-hidden">
                  <div className="flex flex-wrap items-center justify-between gap-3 p-5 pb-0 sm:p-6 sm:pb-0">
                    <div>
                      <h2 className="flex items-center gap-2 text-lg font-semibold">
                        <Box size={18} className="text-keep" aria-hidden /> Your cut in 3D
                      </h2>
                      <p className="mt-1 text-sm text-muted">Built from this video's audio. Drag to rotate.</p>
                    </div>
                    <button type="button" className="btn btn-ghost !py-2 text-sm" onClick={() => setShow3dEdited((v) => !v)} aria-pressed={show3dEdited}>
                      {show3dEdited ? "Show original" : "Apply the cuts"}
                    </button>
                  </div>
                  <CutScene3D
                    mode="interactive"
                    levels={strip.levels}
                    keep={strip.keep}
                    collapsed={show3dEdited}
                    className="h-72 w-full sm:h-80"
                    label={`3D bar chart of this video's loudness, ${show3dEdited ? "with removed sections collapsed" : "before cutting"}.`}
                  />
                </section>
              )}

              <section className="panel p-5 sm:p-6">
                <h2 className="mb-3 text-lg font-semibold">Transcript</h2>
                <TranscriptViewer transcript={transcript} currentTime={originalTime} onSeek={seekOriginal} />
              </section>

              {plan && (
                <details className="panel group p-5 sm:p-6">
                  <summary className="flex cursor-pointer list-none items-center justify-between text-lg font-semibold">
                    Inspect edit decisions ({plan.decisions.length})
                    <ChevronDown size={18} className="transition-transform group-open:rotate-180" aria-hidden />
                  </summary>
                  <p className="mb-4 mt-2 text-sm text-muted">The exact list the renderer used to build your video.</p>
                  <EditDecisionTable decisions={plan.decisions} onSeek={seekOriginal} />
                </details>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

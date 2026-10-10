import { useEffect, useRef, useState } from "react";
import { api, ApiError, type JobAuth } from "../services/api";
import { TERMINAL_STATUSES, type Job } from "../types/api";

interface PollState {
  job: Job | null;
  /** Set while the server is unreachable; polling keeps retrying with backoff. */
  connectionError: string | null;
  /** Fatal error for this job (e.g. 404/410) — polling stops. */
  fatalError: ApiError | null;
}

const BASE_INTERVAL = 1200;
const MAX_INTERVAL = 10000;

/**
 * Poll a job's status until it reaches a terminal state.
 *
 * Responses for a job id that is no longer current are discarded, so a slow
 * reply about an old job can never overwrite the UI for a newer job.
 * ``kick`` restarts polling for the same job (used after a re-render request).
 */
export function useJobPolling(auth: JobAuth | null, initial: Job | null, kick = 0): PollState {
  const [state, setState] = useState<PollState>({ job: initial, connectionError: null, fatalError: null });
  const currentId = useRef<string | null>(null);

  useEffect(() => {
    if (!auth) {
      currentId.current = null;
      setState({ job: null, connectionError: null, fatalError: null });
      return;
    }
    const id = auth.jobId;
    currentId.current = id;
    setState((prev) => ({
      job: prev.job?.job_id === id ? prev.job : initial,
      connectionError: null,
      fatalError: null,
    }));

    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    let failures = 0;
    let stopped = false;

    const tick = async () => {
      controller = new AbortController();
      try {
        const job = await api.getJob(auth, controller.signal);
        if (stopped || currentId.current !== id) return; // stale response
        failures = 0;
        setState({ job, connectionError: null, fatalError: null });
        if (TERMINAL_STATUSES.includes(job.status)) return; // stop polling
        timer = setTimeout(tick, BASE_INTERVAL);
      } catch (err) {
        if (stopped || currentId.current !== id) return;
        const e = err instanceof ApiError ? err : new ApiError(0, "network_error", String(err));
        if (e.isNetwork || e.status >= 500) {
          failures++;
          setState((s) => ({ ...s, connectionError: "Connection to the server was lost. Retrying…" }));
          timer = setTimeout(tick, Math.min(MAX_INTERVAL, BASE_INTERVAL * 2 ** failures));
        } else {
          setState((s) => ({ ...s, fatalError: e, connectionError: null }));
        }
      }
    };
    timer = setTimeout(tick, 300);

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      controller?.abort();
    };
    // `initial` is only a seed for a new job id; it must not restart polling.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth?.jobId, auth?.token, kick]);

  return state;
}

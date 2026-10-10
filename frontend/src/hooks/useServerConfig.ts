import { useEffect, useState } from "react";
import { api, ApiError } from "../services/api";
import type { PublicConfig } from "../types/api";

type ConfigState =
  | { status: "loading"; config: null; error: null }
  | { status: "waking"; config: null; error: string }
  | { status: "ready"; config: PublicConfig; error: null }
  | { status: "error"; config: null; error: string };

let cache: PublicConfig | null = null;

const WAKE_RETRIES = 12; // ~2 minutes: free hosts can take a minute to start after sleeping
const WAKE_DELAY_MS = 10_000;

/** Limits and defaults published by the backend (/api/config), retried while a sleeping server wakes up. */
export function useServerConfig(): ConfigState & { retry: () => void } {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<ConfigState>(
    cache ? { status: "ready", config: cache, error: null } : { status: "loading", config: null, error: null },
  );

  useEffect(() => {
    if (cache) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let tries = 0;
    const load = () => {
      api
        .config()
        .then((cfg) => {
          cache = cfg;
          if (alive) setState({ status: "ready", config: cfg, error: null });
        })
        .catch((e: ApiError) => {
          if (!alive) return;
          const transient = e.isNetwork || e.status === 502 || e.status === 503 || e.status === 504;
          if (transient && tries++ < WAKE_RETRIES) {
            setState({ status: "waking", config: null, error: "The free server is waking up. This can take about a minute…" });
            timer = setTimeout(load, WAKE_DELAY_MS);
          } else {
            setState({ status: "error", config: null, error: e.message });
          }
        });
    };
    setState({ status: "loading", config: null, error: null });
    load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [attempt]);

  return { ...state, retry: () => setAttempt((a) => a + 1) };
}

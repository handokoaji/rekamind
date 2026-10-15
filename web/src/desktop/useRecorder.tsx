import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { desktop, onChanged } from "./bridge";
import type { UiState } from "./types";
import { t } from "../lib/i18n";

interface Ctx {
  state: UiState | null;
  error: string | null;
  start: (title: string) => Promise<void>;
  stop: () => Promise<void>;
  retry: (dir: string) => Promise<void>;
  discard: (dir: string) => Promise<void>;
  dismiss: () => Promise<void>;
}
const RecorderCtx = createContext<Ctx | null>(null);

export function useRecorder(): Ctx {
  const c = useContext(RecorderCtx);
  if (!c) throw new Error("useRecorder must be used inside RecorderProvider");
  return c;
}

/** Live while recording/uploading (4 Hz, for the level meters), near-silent otherwise: an idle
 *  app does one tiny call every few seconds, and none at all while the window is hidden. */
export function RecorderProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<UiState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const s = await desktop.state();
      if (alive.current) { setState(s); setError(null); }
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : t("Tidak bisa membaca status perekam."));
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void refresh();
    let off: (() => void) | undefined;
    void onChanged(() => void refresh()).then((u) => { off = u; if (!alive.current) u(); });
    return () => { alive.current = false; off?.(); };
  }, [refresh]);

  const busy = state?.phase === "recording" || state?.phase === "uploading";
  useEffect(() => {
    const every = busy ? 250 : 3000;
    const tick = () => { if (document.visibilityState === "visible") void refresh(); };
    const id = setInterval(tick, every);
    document.addEventListener("visibilitychange", tick);
    return () => { clearInterval(id); document.removeEventListener("visibilitychange", tick); };
  }, [busy, refresh]);

  const wrap = useCallback((f: () => Promise<void>) => async () => { await f(); await refresh(); }, [refresh]);
  const value = useMemo<Ctx>(() => ({
    state, error,
    start: async (t) => { await desktop.start(t); await refresh(); },
    stop: wrap(desktop.stop),
    retry: async (d) => { await desktop.retry(d); await refresh(); },
    discard: async (d) => { await desktop.discard(d); await refresh(); },
    dismiss: wrap(desktop.dismiss),
  }), [state, error, refresh, wrap]);

  return <RecorderCtx.Provider value={value}>{children}</RecorderCtx.Provider>;
}

/** Cheap "is a recording running" for components that only need that one fact (null-safe outside desktop). */
export function useDesktopRecording(): boolean {
  return useContext(RecorderCtx)?.state?.phase === "recording";
}

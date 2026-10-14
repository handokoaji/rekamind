import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { setAuthToken, setBackendUrl } from "../lib/api";
import { desktop } from "./bridge";

type Status = "starting" | "ready" | "error";
interface Ctx {
  status: Status;
  error: string | null;
  /** True once the backend has answered at least once; after that, restarts never blank the page. */
  everReady: boolean;
  /** Which kind of backend the shell chose; null until the shell has said. "local" backends are started and stopped by the shell, so being down is normal, not an error. */
  mode: "local" | "remote" | null;
  retry: () => void;
}
const BackendCtx = createContext<Ctx>({ status: "ready", error: null, everReady: true, mode: "remote", retry: () => undefined });
export const useBackendReady = () => useContext(BackendCtx);

/** In the desktop app the shell owns which server to talk to, and a local backend only runs on
 *  demand, so the UI asks for it to be up before it tries to load anything. */
export function BackendProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("starting");
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"local" | "remote" | null>(null);
  const qc = useQueryClient();
  const everReady = useRef(false);
  const inFlight = useRef(false);

  const start = useCallback(() => {
    if (inFlight.current) return;
    inFlight.current = true;
    setStatus("starting");
    desktop.settings()
      .then((s) => { setBackendUrl(s.server_url); setAuthToken(s.auth_token); setMode(s.settings.mode); return desktop.ensureBackend(); })
      .then(() => { everReady.current = true; setStatus("ready"); void qc.invalidateQueries({ queryKey: ["health"] }); })
      .catch((e: unknown) => { setError(e instanceof Error ? e.message : "Tidak bisa menyalakan layanan."); setStatus("error"); })
      .finally(() => { inFlight.current = false; });
  }, [qc]);
  useEffect(start, [start]);

  return <BackendCtx.Provider value={{ status, error, everReady: everReady.current, mode, retry: start }}>{children}</BackendCtx.Provider>;
}

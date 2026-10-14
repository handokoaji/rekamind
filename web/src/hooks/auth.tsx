import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { api, ApiError, onUnauthorized, setAuthToken } from "../lib/api";
import { useBackendReady } from "../desktop/backend";
import { desktop, isDesktop } from "../desktop/bridge";
import type { Me } from "../lib/types";

interface Ctx {
  me: Me;
  logout: () => Promise<void>;
  isSuperadmin: boolean;
  /** Multi-user admin features exist only on a Google-login server; a single-user local backend has no one else to manage. */
  canAdmin: boolean;
}
const AuthCtx = createContext<Ctx | null>(null);

export function useAuth(): Ctx {
  const c = useContext(AuthCtx);
  if (!c) throw new Error("useAuth must be used inside an authenticated tree");
  return c;
}

const LOCAL_ME: Me = { id: "local", email: "", name: null, picture: null, role: "superadmin", auth_mode: "local_token" };

export type AuthState = { status: "loading" } |  { status: "signed-out" } | { status: "error"; error: Error } | { status: "ready"; me: Me };

/** One place decides whether the app shows a login screen: /api/me. Any other request that gets a 401
 *  (a session that expired while the page was open) just re-asks it. */
export function useAuthState(): AuthState {
  const qc = useQueryClient();
  // In the desktop app the shell decides which server (and which credential) to use, and a local
  // backend starts on demand: asking before it is up would be a spurious "cannot connect".
  const backend = useBackendReady();
  const local = backend.mode === "local";
  const up = backend.mode !== null && (local || backend.status === "ready" || backend.everReady);
  const q = useQuery({
    queryKey: ["me"], queryFn: api.me,
    enabled: up && !local, retry: false, staleTime: 60_000, refetchOnWindowFocus: true,
  });
  useEffect(() => onUnauthorized(() => { void qc.invalidateQueries({ queryKey: ["me"] }); }), [qc]);
  // The desktop app's own backend serves exactly one person (the one at this keyboard) and is switched
  // off during recordings, so there is nothing to ask and no one else to sign in. The shell shows
  // "starting" / "cannot start" itself, and the backend still demands the local secret.
  if (local) return { status: "ready", me: LOCAL_ME };
  if (backend.mode === null && isDesktop()) return { status: "loading" };
  if (backend.status === "error" && !backend.everReady) return { status: "error", error: new Error(backend.error ?? "Tidak bisa menyalakan layanan.") };
  if (!up) return { status: "loading" };
  if (q.isPending) return { status: "loading" };
  if (q.error instanceof ApiError && q.error.status === 401) return { status: "signed-out" };
  // A later refresh failing (backend stopped while idle, network blip) must not throw away a good session.
  if (q.error && !q.data) return { status: "error", error: q.error };
  return { status: "ready", me: q.data! };
}

export function AuthProvider({ me, children }: { me: Me; children: ReactNode }) {
  const qc = useQueryClient();
  const logout = async () => {
    try { await api.logout(); } catch { /* already signed out is fine */ }
    if (isDesktop()) {
      // The shell owns the credential: forget it there too, then show the login screen again.
      try { await desktop.logout(); } catch { /* nothing more to forget */ }
      setAuthToken(null);
        qc.clear();
      return;
    }
    qc.clear();
    window.location.assign("/");
  };
  return <AuthCtx.Provider value={{ me, logout, isSuperadmin: me.role === "superadmin", canAdmin: me.role === "superadmin" && me.auth_mode === "google" }}>{children}</AuthCtx.Provider>;
}

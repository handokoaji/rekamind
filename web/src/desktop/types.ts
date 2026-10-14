/** Mirrors Rust's `UiState` (recorder/src/controller.rs). `desktop/contract/ui-state.json` is the
 *  golden file both sides test against, so a change on either side fails a test, not the app. */
export type Phase = "idle" | "recording" | "uploading" | "done" | "needs_attention";
export type SourceId = "mic" | "speaker";
export type SourceKind = "recording" | "reconnecting" | "unavailable" | "failed";

export interface SourceView {
  source: SourceId; label: string; level: number; state: SourceKind; message: string | null; seconds: number;
}
export interface UploadView { step: string; fraction: number }
export interface Outcome { title: string; dir: string; meeting_id: string | null; error: string | null; warnings: string[] }
export interface Pending { dir: string; title: string; created_unix: number; crashed: boolean }
export interface UiState {
  phase: Phase; title: string | null; elapsed_secs: number; sources: SourceView[];
  upload: UploadView | null; last: Outcome | null; pending: Pending[];
}

export interface DesktopSettings {
  mode: "local" | "remote"; server: string; local_program: string; local_args: string[]; local_port: number;
  language: "id" | "en"; local_user_name: string; auto_process: boolean; hotkey: string;
}
export interface SettingsView { settings: DesktopSettings; server_url: string; auth_token: string | null; recordings_dir: string; hotkey_error: string | null }
export interface LoginResult { email: string; token: string; remembered: boolean }

const PHASES: Phase[] = ["idle", "recording", "uploading", "done", "needs_attention"];
const KINDS: SourceKind[] = ["recording", "reconnecting", "unavailable", "failed"];
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const nullOr = (f: (v: unknown) => boolean) => (v: unknown) => v === null || f(v);

/** Runtime check used by the contract test (and available for defensive use at the IPC boundary). */
export function isUiState(x: unknown): x is UiState {
  const o = x as Record<string, unknown>;
  if (!o || typeof o !== "object") return false;
  const source = (s: unknown) => {
    const v = s as Record<string, unknown>;
    return !!v && (v.source === "mic" || v.source === "speaker") && isStr(v.label) && isNum(v.level) && KINDS.includes(v.state as SourceKind) && nullOr(isStr)(v.message) && isNum(v.seconds);
  };
  const outcome = (s: unknown) => {
    const v = s as Record<string, unknown>;
    return !!v && isStr(v.title) && isStr(v.dir) && nullOr(isStr)(v.meeting_id) && nullOr(isStr)(v.error) && Array.isArray(v.warnings) && v.warnings.every(isStr);
  };
  const upload = (s: unknown) => { const v = s as Record<string, unknown>; return !!v && isStr(v.step) && isNum(v.fraction); };
  const pending = (s: unknown) => { const v = s as Record<string, unknown>; return !!v && isStr(v.dir) && isStr(v.title) && isNum(v.created_unix) && typeof v.crashed === "boolean"; };
  return PHASES.includes(o.phase as Phase) && nullOr(isStr)(o.title) && isNum(o.elapsed_secs)
    && Array.isArray(o.sources) && o.sources.every(source) && nullOr(upload)(o.upload) && nullOr(outcome)(o.last)
    && Array.isArray(o.pending) && o.pending.every(pending)
    && Object.keys(o).sort().join() === "elapsed_secs,last,pending,phase,sources,title,upload";
}

import type { DesktopSettings, EngineCheck, EngineState, LoginResult, SettingsView, UiState } from "./types";

/** True only inside the Tauri shell. In a normal browser every desktop feature stays hidden. */
export const isDesktop = (): boolean => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

type Args = Record<string, unknown>;

/** Loaded on demand so the browser build never pays for the Tauri client. */
async function invoke<T>(cmd: string, args?: Args): Promise<T> {
  const { invoke: tauriInvoke } = await import("@tauri-apps/api/core");
  try {
    return await tauriInvoke<T>(cmd, args);
  } catch (e) {
    // Rust returns plain strings for expected errors ("Perekaman sedang berjalan.").
    throw new Error(typeof e === "string" ? e : e instanceof Error ? e.message : "Terjadi kesalahan pada aplikasi desktop.");
  }
}

/** Subscribe to "something changed" pushes from the shell. Best effort: polling covers a failure. */
export async function onChanged(fn: () => void, event = "recorder://changed"): Promise<() => void> {
  try {
    const { listen } = await import("@tauri-apps/api/event");
    return await listen(event, fn);
  } catch {
    return () => undefined;
  }
}

export const desktop = {
  state: () => invoke<UiState>("recorder_state"),
  start: (title: string) => invoke<void>("recorder_start", { title }),
  stop: () => invoke<void>("recorder_stop"),
  retry: (dir: string) => invoke<void>("recorder_retry", { dir }),
  discard: (dir: string) => invoke<void>("recorder_discard", { dir }),
  dismiss: () => invoke<void>("recorder_dismiss"),
  settings: () => invoke<SettingsView>("settings_get"),
  saveSettings: (settings: DesktopSettings) => invoke<SettingsView>("settings_set", { settings }),
  ensureBackend: () => invoke<void>("backend_ensure"),
  engines: () => invoke<EngineState>("engines_status"),
  checkEngines: () => invoke<EngineCheck>("engines_check"),
  installEngines: (kind: "cpu" | "cuda", diarize: boolean) => invoke<void>("engines_install", { kind, diarize }),
  warmupModel: () => invoke<void>("engines_warmup"),
  cancelEngines: () => invoke<void>("engines_cancel"),
  /** undefined leaves a secret alone; "" removes it. */
  setSecrets: (s: { llmApiKey?: string; hfToken?: string }) => invoke<SettingsView>("secrets_set", { llmApiKey: s.llmApiKey, hfToken: s.hfToken }),
  login: () => invoke<LoginResult>("auth_login"),
  logout: () => invoke<void>("auth_logout"),
};

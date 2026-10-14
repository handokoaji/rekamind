import type { DesktopSettings, LoginResult, SettingsView, UiState } from "./types";

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
export async function onChanged(fn: () => void): Promise<() => void> {
  try {
    const { listen } = await import("@tauri-apps/api/event");
    return await listen("recorder://changed", fn);
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
  login: () => invoke<LoginResult>("auth_login"),
  logout: () => invoke<void>("auth_logout"),
};

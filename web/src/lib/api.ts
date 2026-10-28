import type {
  AdminUser, Capabilities, ExportFormat, Integration, IntegrationKind, IntegrationStatus, Me, Meeting, MeetingDetail, Participant, Role, Scope, PushResult, Source, Task, TaskLinkInfo, TaskPatch, TaskStatus, TaskWithMeeting,
} from "./types";
import { t } from "./i18n";

const KEY = "rekamind.backendUrl";

/** Where the API lives. Empty = same origin (the normal case: the backend serves this UI). */
export function getBackendUrl(): string {
  try { return localStorage.getItem(KEY) ?? ""; } catch { return ""; }
}
/** Sub-path the app is served under ("" at the root), from vite `base`. */
export const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");
/** Prefix for API/auth calls: the configured backend, else this app's own origin and sub-path. */
export const apiRoot = (): string => getBackendUrl() || BASE;
export function setBackendUrl(url: string): void {
  try { url ? localStorage.setItem(KEY, url) : localStorage.removeItem(KEY); } catch { /* storage blocked: stay on same origin */ }
}
/** Accepts only http(s) origins so a typo or hostile value cannot point requests at another scheme. */
export function normalizeBackendUrl(raw: string): string | null {
  const v = raw.trim();
  if (!v) return "";
  try {
    const u = new URL(v);
    return u.protocol === "http:" || u.protocol === "https:" ? u.origin : null;
  } catch { return null; }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

/** The desktop app logs in out of band and hands us a bearer token; a browser uses its session cookie
 *  instead, which needs no code here at all. */
let bearer: string | null = null;
export const setAuthToken = (tok: string | null) => { bearer = tok; };
function authHeaders(): Record<string, string> { return bearer ? { authorization: `Bearer ${bearer}` } : {}; }

/** Called whenever the server says "not signed in": the UI then shows the login screen. */
const unauthorized = new Set<() => void>();
export const onUnauthorized = (fn: () => void) => { unauthorized.add(fn); return () => { unauthorized.delete(fn); }; };

function messageFrom(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return t("Isian belum valid. Periksa kembali data yang dimasukkan.");
  if (status === 413) return t("File terlalu besar.");
  if (status >= 500) return t("Server mengalami masalah. Coba lagi sebentar lagi.");
  return t("Permintaan gagal ({status}).", { status });
}

async function send(method: string, path: string, body?: unknown): Promise<{ res: Response; data: unknown }> {
  let res: Response;
  try {
    res = await fetch(`${apiRoot()}${path.startsWith("/../") ? path.slice(3) : `/api${path}`}`, {
      method,
      headers: { ...authHeaders(), ...(body !== undefined ? { "content-type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, t("Tidak dapat terhubung ke server. Periksa koneksi atau alamat server di Pengaturan."));
  }
  if (res.status === 204) return { res, data: undefined };
  const data = await res.json().catch(() => null);
  // /me is how the app *asks* whether it is signed in; reacting to its own 401 would ask again forever.
  if (res.status === 401 && path !== "/me") unauthorized.forEach((f) => f());
  if (!res.ok) throw new ApiError(res.status, messageFrom(data, res.status));
  return { res, data };
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  return (await send(method, path, body)).data as T;
}

function meetingsPath(q: string, status: string, scope: Scope, offset: number, limit: number): string {
  const p = new URLSearchParams();
  if (offset) p.set("offset", String(offset));
  if (limit !== 50) p.set("limit", String(limit));
  if (q) p.set("q", q);
  if (status) p.set("status", status);
  if (scope === "all") p.set("scope", "all");
  return `/meetings${p.size ? `?${p}` : ""}`;
}

export const api = {
  health: () => request<{ status: string; version: string }>("GET", "/health"),
  capabilities: () => request<Capabilities>("GET", "/capabilities"),
  me: () => request<Me>("GET", "/me"),
  logout: () => request<void>("POST", "/../auth/logout"),
  adminUsers: () => request<AdminUser[]>("GET", "/admin/users"),
  inviteUser: (email: string, role: Role) => request<AdminUser>("POST", "/admin/users", { email, role }),
  patchUser: (id: string, patch: { role?: Role; disabled?: boolean }) => request<AdminUser>("PATCH", `/admin/users/${id}`, patch),
  meetings: (q = "", status = "", scope: Scope = "mine", offset = 0, limit = 50) => request<Meeting[]>("GET", meetingsPath(q, status, scope, offset, limit)),
  /** One page, and how many meetings there are in all (X-Total-Count; null from a server that does not send it). */
  meetingsPage: async (q = "", status = "", scope: Scope = "mine", offset = 0, limit = 50): Promise<{ items: Meeting[]; total: number | null }> => {
    const { res, data } = await send("GET", meetingsPath(q, status, scope, offset, limit));
    const header = res.headers.get("x-total-count");
    return { items: data as Meeting[], total: header !== null && Number.isFinite(Number(header)) ? Number(header) : null };
  },
  integrationStatus: () => request<IntegrationStatus>("GET", "/integrations/status"),
  integrations: () => request<Integration[]>("GET", "/integrations"),
  createIntegration: (b: { kind: IntegrationKind; name: string; config: Record<string, unknown>; secret?: string }) => request<Integration>("POST", "/integrations", b),
  patchIntegration: (id: string, b: { name?: string; config?: Record<string, unknown>; secret?: string; enabled?: boolean }) => request<Integration>("PATCH", `/integrations/${id}`, b),
  deleteIntegration: (id: string) => request<void>("DELETE", `/integrations/${id}`),
  testIntegration: (id: string) => request<{ ok: boolean; message: string }>("POST", `/integrations/${id}/test`),
  push: (meetingId: string, integrationId: string, taskIds?: string[]) =>
    request<{ integration: string; results: PushResult[] }>("POST", `/meetings/${meetingId}/push`, { integration_id: integrationId, task_ids: taskIds }),
  links: (meetingId: string) => request<TaskLinkInfo[]>("GET", `/meetings/${meetingId}/links`),
  /** Fetched with the same credentials as every other call (the desktop app uses a bearer token, not a cookie). */
  exportMeeting: async (id: string, o: { format: ExportFormat; transcript: boolean; allTasks: boolean }): Promise<{ blob: Blob; filename: string }> => {
    const q = new URLSearchParams({ format: o.format, transcript: String(o.transcript), tasks: o.allTasks ? "all" : "confirmed" });
    let res: Response;
    try { res = await fetch(`${apiRoot()}/api/meetings/${id}/export?${q}`, { headers: authHeaders() }); }
    catch { throw new ApiError(0, t("Tidak dapat terhubung ke server.")); }
    if (!res.ok) throw new ApiError(res.status, messageFrom(await res.json().catch(() => null), res.status));
    const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? `rekamind.${o.format}`;
    return { blob: await res.blob(), filename: name };
  },
  meeting: (id: string) => request<MeetingDetail>("GET", `/meetings/${id}`),
  createMeeting: (b: { title: string; language: string; local_user_name?: string | null }) =>
    request<Meeting>("POST", "/meetings", b),
  renameMeeting: (id: string, title: string) => request<Meeting>("PATCH", `/meetings/${id}`, { title }),
  setNumSpeakers: (id: string, numSpeakers: number | null) => request<Meeting>("PATCH", `/meetings/${id}`, { num_speakers: numSpeakers }),
  finishMeeting: (id: string) => request<Meeting>("POST", `/meetings/${id}/finish`),
  deleteMeeting: (id: string) => request<void>("DELETE", `/meetings/${id}`),
  /** Removes audio, transcript and tasks for good (the plain delete is undoable and purged after 30 days). */
  purgeMeeting: (id: string) => request<void>("DELETE", `/meetings/${id}?permanent=true`),
  restoreMeeting: (id: string) => request<Meeting>("POST", `/meetings/${id}/restore`),
  /** stage "extract" redoes only the summary and tasks (the transcript is kept). */
  process: (id: string, stage: "all" | "extract" = "all") => request("POST", `/meetings/${id}/process${stage === "extract" ? "?stage=extract" : ""}`),
  renameParticipant: (id: string, name: string | null) => request<Participant>("PATCH", `/participants/${id}`, { name }),
  tasks: (status?: TaskStatus, scope: Scope = "mine") => {
    const p = new URLSearchParams();
    if (status) p.set("status", status);
    if (scope === "all") p.set("scope", "all");
    return request<TaskWithMeeting[]>("GET", `/tasks${p.size ? `?${p}` : ""}`);
  },
  patchTask: (id: string, patch: TaskPatch) => request<Task>("PATCH", `/tasks/${id}`, patch),
  /** An <audio src> cannot send the bearer header (the desktop app has no cookie), so the file is fetched
   *  with the same credentials as every other call and played from a blob URL. */
  fetchAudio: async (id: string, source: Source): Promise<Blob> => {
    let res: Response;
    try { res = await fetch(`${apiRoot()}/api/meetings/${id}/audio/${source}`, { headers: authHeaders() }); }
    catch { throw new ApiError(0, t("Tidak dapat terhubung ke server.")); }
    if (!res.ok) throw new ApiError(res.status, res.status === 404 ? t("Audio tidak tersedia untuk rapat ini.") : messageFrom(await res.json().catch(() => null), res.status));
    return res.blob();
  },
};

/** PUT with progress (fetch cannot report upload progress). */
export function uploadAudio(
  id: string, source: Source, file: File, onProgress: (fraction: number) => void, signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `${apiRoot()}/api/meetings/${id}/audio/${source}`);
    for (const [k, v] of Object.entries(authHeaders())) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve();
      let body: unknown = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* non-JSON error body */ }
      reject(new ApiError(xhr.status, messageFrom(body, xhr.status)));
    };
    xhr.onerror = () => reject(new ApiError(0, t("Unggahan terputus. Periksa koneksi lalu coba lagi.")));
    xhr.onabort = () => reject(new DOMException(t("Dibatalkan"), "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(file);
  });
}

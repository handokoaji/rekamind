import type {
  Capabilities, Meeting, MeetingDetail, Participant, Source, Task, TaskPatch, TaskStatus, TaskWithMeeting,
} from "./types";

const KEY = "rekamind.backendUrl";

/** Where the API lives. Empty = same origin (the normal case: the backend serves this UI). */
export function getBackendUrl(): string {
  try { return localStorage.getItem(KEY) ?? ""; } catch { return ""; }
}
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

// Placeholder for the OAuth bearer token; every request already flows through here.
function authHeaders(): Record<string, string> { return {}; }

function messageFrom(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "Isian belum valid. Periksa kembali data yang dimasukkan.";
  if (status === 413) return "File terlalu besar.";
  if (status >= 500) return "Server mengalami masalah. Coba lagi sebentar lagi.";
  return `Permintaan gagal (${status}).`;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${getBackendUrl()}/api${path}`, {
      method,
      headers: { ...authHeaders(), ...(body !== undefined ? { "content-type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Tidak dapat terhubung ke server. Periksa koneksi atau alamat server di Pengaturan.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, messageFrom(data, res.status));
  return data as T;
}

export const api = {
  health: () => request<{ status: string; version: string }>("GET", "/health"),
  capabilities: () => request<Capabilities>("GET", "/capabilities"),
  meetings: (q = "", status = "") => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (status) p.set("status", status);
    return request<Meeting[]>("GET", `/meetings${p.size ? `?${p}` : ""}`);
  },
  meeting: (id: string) => request<MeetingDetail>("GET", `/meetings/${id}`),
  createMeeting: (b: { title: string; language: string; local_user_name?: string | null }) =>
    request<Meeting>("POST", "/meetings", b),
  renameMeeting: (id: string, title: string) => request<Meeting>("PATCH", `/meetings/${id}`, { title }),
  finishMeeting: (id: string) => request<Meeting>("POST", `/meetings/${id}/finish`),
  deleteMeeting: (id: string) => request<void>("DELETE", `/meetings/${id}`),
  restoreMeeting: (id: string) => request<Meeting>("POST", `/meetings/${id}/restore`),
  process: (id: string) => request("POST", `/meetings/${id}/process`),
  renameParticipant: (id: string, name: string | null) => request<Participant>("PATCH", `/participants/${id}`, { name }),
  tasks: (status?: TaskStatus) => request<TaskWithMeeting[]>("GET", `/tasks${status ? `?status=${status}` : ""}`),
  patchTask: (id: string, patch: TaskPatch) => request<Task>("PATCH", `/tasks/${id}`, patch),
  audioUrl: (id: string, source: Source) => `${getBackendUrl()}/api/meetings/${id}/audio/${source}`,
};

/** PUT with progress (fetch cannot report upload progress). */
export function uploadAudio(
  id: string, source: Source, file: File, onProgress: (fraction: number) => void, signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `${getBackendUrl()}/api/meetings/${id}/audio/${source}`);
    for (const [k, v] of Object.entries(authHeaders())) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve();
      let body: unknown = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* non-JSON error body */ }
      reject(new ApiError(xhr.status, messageFrom(body, xhr.status)));
    };
    xhr.onerror = () => reject(new ApiError(0, "Unggahan terputus. Periksa koneksi lalu coba lagi."));
    xhr.onabort = () => reject(new DOMException("Dibatalkan", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(file);
  });
}

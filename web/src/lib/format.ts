const dateFmt = new Intl.DateTimeFormat("id-ID", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const timeFmt = new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "long", year: "numeric" });

export const formatDateTime = (iso: string) => `${dateFmt.format(new Date(iso))}, ${timeFmt.format(new Date(iso))}`;
/** "2026-10-23" -> "23 Oktober 2026". Parsed as a calendar date, never shifted by timezone. */
export function formatDay(ymd: string): string {
  const [y, m, d] = ymd.split("-").map(Number);
  return dayFmt.format(new Date(y!, (m ?? 1) - 1, d));
}
/** 330000 -> "05:30"; 3723000 -> "1:02:03" */
export function formatClock(ms: number): string {
  const s = Math.floor(ms / 1000);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return s >= 3600 ? `${Math.floor(s / 3600)}:${mm}:${ss}` : `${mm}:${ss}`;
}
/** 150 -> "2 jam 30 menit" */
export function formatMinutes(total: number): string {
  const h = Math.floor(total / 60), m = total % 60;
  if (h && m) return `${h} jam ${m} menit`;
  return h ? `${h} jam` : `${m} menit`;
}
export const percent = (x: number) => `${Math.round(x * 100)}%`;
export const fileTitle = (name: string) => name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();

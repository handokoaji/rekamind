import { intlLocale, t } from "./i18n";
/** The zone meetings are shown in (IANA name). undefined = this device's own zone. */
let displayZone: string | undefined;
export function setDisplayTimeZone(zone: string | undefined): void { displayZone = zone; }
export const getDisplayTimeZone = () => displayZone;

const fmt = (o: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat(intlLocale(), { ...o, timeZone: displayZone });

/** "Rab, 15 Okt 2026, 09.30 WIB": always names the zone, so a screenshot or a colleague elsewhere is unambiguous. */
export const formatDateTime = (iso: string) => {
  const d = new Date(iso);
  return `${fmt({ weekday: "short", day: "numeric", month: "short", year: "numeric" }).format(d)}, ${fmt({ hour: "2-digit", minute: "2-digit", timeZoneName: "short" }).format(d)}`;
};
/** "2026-10-23" -> "23 Oktober 2026". Parsed as a calendar date, never shifted by timezone. */
export function formatDay(ymd: string): string {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Intl.DateTimeFormat(intlLocale(), { day: "numeric", month: "long", year: "numeric" }).format(new Date(y!, (m ?? 1) - 1, d));
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
  if (h && m) return t("{h} jam {m} menit", { h, m });
  return h ? t("{h} jam", { h }) : t("{m} menit", { m });
}
export const percent = (x: number) => `${Math.round(x * 100)}%`;
export const fileTitle = (name: string) => name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();

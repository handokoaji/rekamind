import { t, translated } from "./i18n";
import type { MeetingStatus, Priority, TaskStatus } from "./types";

/** Plain language, no jargon ("diarisasi", "ASR", "job"). Indonesian source text; shown translated via i18n. */
const rawStatus: Record<MeetingStatus, string> = {
  recording: "Sedang merekam",
  recorded: "Siap diproses",
  queued: "Menunggu giliran",
  processing: "Sedang diproses",
  review: "Perlu ditinjau",
  done: "Selesai",
  failed: "Gagal",
};
const rawStage: Record<string, string> = {
  transcribing: "Menulis transkrip",
  diarizing: "Mengenali pembicara",
  merging: "Menyusun percakapan",
  extracting: "Mencari ringkasan dan task",
};
const rawPriority: Record<Priority, string> = { low: "Rendah", medium: "Sedang", high: "Tinggi" };
const rawTaskStatus: Record<TaskStatus, string> = {
  suggested: "Perlu ditinjau", confirmed: "Dikonfirmasi", rejected: "Ditolak",
};

export const statusLabel = translated(rawStatus);
export const stageLabel = translated(rawStage);
export const priorityLabel = translated(rawPriority);
export const taskStatusLabel = translated(rawTaskStatus);
export const confidenceLabel = (c: number) => t(c >= 0.8 ? "Yakin" : c >= 0.5 ? "Cukup yakin" : "Ragu");
/** Every source string above, for the "all translated" guard test. */
export const LABEL_SOURCES: string[] = [...Object.values(rawStatus), ...Object.values(rawStage), ...Object.values(rawPriority), ...Object.values(rawTaskStatus)];

import type { MeetingStatus, Priority, TaskStatus } from "./types";

/** Plain language, no jargon ("diarisasi", "ASR", "job"). One place to translate later. */
export const statusLabel: Record<MeetingStatus, string> = {
  recording: "Sedang merekam",
  recorded: "Siap diproses",
  queued: "Menunggu giliran",
  processing: "Sedang diproses",
  review: "Perlu ditinjau",
  done: "Selesai",
  failed: "Gagal",
};
export const stageLabel: Record<string, string> = {
  transcribing: "Menulis transkrip",
  diarizing: "Mengenali pembicara",
  merging: "Menyusun percakapan",
  extracting: "Mencari ringkasan dan task",
};
export const priorityLabel: Record<Priority, string> = { low: "Rendah", medium: "Sedang", high: "Tinggi" };
export const taskStatusLabel: Record<TaskStatus, string> = {
  suggested: "Perlu ditinjau", confirmed: "Dikonfirmasi", rejected: "Ditolak",
};
export const confidenceLabel = (c: number) => (c >= 0.8 ? "Yakin" : c >= 0.5 ? "Cukup yakin" : "Ragu");

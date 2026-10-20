import { Download, FileText } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";
import { t } from "../lib/i18n";
import type { ExportFormat } from "../lib/types";
import { Button } from "./ui/Button";
import { Dialog } from "./ui/Dialog";

const formats = (): { value: ExportFormat; label: string; hint: string }[] => [
  { value: "docx", label: "Word (.docx)", hint: t("Notulen siap dibagikan atau dicetak.") },
  { value: "md", label: "Markdown (.md)", hint: t("Teks biasa; cocok untuk wiki, Notion, Obsidian, atau GitHub.") },
  { value: "json", label: "JSON (.json)", hint: t("Data lengkap untuk skrip atau sistem lain (skema rekamind.meeting/v1).") },
];

function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function ExportDialog({ meetingId, open, onOpenChange }: { meetingId: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [format, setFormat] = useState<ExportFormat>("docx");
  const [transcript, setTranscript] = useState(true);
  const [allTasks, setAllTasks] = useState(false);
  const [busy, setBusy] = useState(false);

  async function go() {
    setBusy(true);
    try {
      const { blob, filename } = await api.exportMeeting(meetingId, { format, transcript, allTasks });
      save(blob, filename);
      toast.success(t("{filename} diunduh.", { filename }));
      onOpenChange(false);
    } catch (e) { toast.error(e instanceof Error ? e.message : t("Gagal mengekspor")); } finally { setBusy(false); }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("Ekspor rapat")} description={t("Ringkasan, poin penting, keputusan, jalannya rapat, task, dan (bila dipilih) transkrip dalam satu berkas.")}>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium">{t("Format")}</legend>
        {formats().map((f) => (
          <label key={f.value} className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3 has-[:checked]:border-primary has-[:checked]:bg-primary-soft">
            <input type="radio" name="fmt" className="mt-1 accent-[var(--primary)]" checked={format === f.value} onChange={() => setFormat(f.value)} />
            <span><span className="block text-sm font-medium">{f.label}</span><span className="block text-xs text-muted">{f.hint}</span></span>
          </label>))}
      </fieldset>
      <div className="mt-4 flex flex-col gap-2 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" className="size-4 accent-[var(--primary)]" checked={transcript} onChange={(e) => setTranscript(e.target.checked)} /> {t("Sertakan transkrip lengkap")}</label>
        <label className="flex items-start gap-2"><input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]" checked={allTasks} onChange={(e) => setAllTasks(e.target.checked)} />
          <span>{t("Sertakan juga task yang belum dikonfirmasi")}<span className="block text-xs text-muted">{t("Ditandai jelas sebagai saran AI. Bawaan: hanya task yang sudah Anda konfirmasi.")}</span></span></label>
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("Batal")}</Button>
        <Button variant="primary" loading={busy} onClick={() => void go()}><Download className="size-4" aria-hidden /> {t("Unduh")}</Button>
      </div>
    </Dialog>
  );
}

export const ExportIcon = FileText;

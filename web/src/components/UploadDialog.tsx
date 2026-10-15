import { useQueryClient } from "@tanstack/react-query";
import { FileAudio, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { useCapabilities } from "../hooks/queries";
import { api, uploadAudio } from "../lib/api";
import { fileTitle } from "../lib/format";
import { t } from "../lib/i18n";
import { Button } from "./ui/Button";
import { Dialog } from "./ui/Dialog";
import { Field, Input, Select } from "./ui/Field";
import { ProgressBar } from "./ui/Feedback";

export function UploadDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (o: boolean) => void; onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const caps = useCapabilities();
  const ready = caps.data?.processing_ready ?? false;
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("id");
  const [me, setMe] = useState("");
  const [autoProcess, setAutoProcess] = useState(true);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string>();
  const abort = useRef<AbortController | null>(null);
  const [dragging, setDragging] = useState(false);

  const pick = (f: File | undefined) => {
    if (!f) return;
    if (f.type && !f.type.startsWith("audio/") && !f.type.startsWith("video/")) {
      setError(t("Pilih file audio (WAV, MP3, M4A, OGG…)."));
      return;
    }
    setError(undefined);
    setFile(f);
    setTitle((prev) => prev || fileTitle(f.name));
  };

  const busy = progress !== null;
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || busy) return;
    setError(undefined);
    setProgress(0);
    abort.current = new AbortController();
    let createdId: string | undefined;
    try {
      const m = await api.createMeeting({ title: title.trim() || fileTitle(file.name), language, local_user_name: me.trim() || null });
      createdId = m.id;
      // An imported file is one mixed recording, so it goes in as the "speaker" channel and gets diarized.
      await uploadAudio(m.id, "speaker", file, setProgress, abort.current.signal);
      await api.finishMeeting(m.id);
      if (autoProcess && ready) await api.process(m.id);
      await qc.invalidateQueries({ queryKey: ["meetings"] });
      toast.success(autoProcess && ready ? t("Rekaman diunggah dan mulai diproses.") : t("Rekaman diunggah."));
      onOpenChange(false);
      onCreated(m.id);
    } catch (err) {
      if (createdId) void api.deleteMeeting(createdId).catch(() => undefined); // no half-created meeting left behind
      setError(err instanceof DOMException ? t("Unggahan dibatalkan.") : err instanceof Error ? err.message : t("Gagal mengunggah."));
    } finally {
      setProgress(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o && busy) abort.current?.abort(); onOpenChange(o); }}
      title={t("Rapat baru dari rekaman")} description={t("Unggah file rekaman rapat. Hasilnya muncul setelah diproses.")}>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <label
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files[0]); }}
          className={`flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors focus-within:outline-2 focus-within:outline-primary ${dragging ? "border-primary bg-primary-soft" : "border-border hover:border-muted"}`}>
          <input type="file" accept="audio/*,video/mp4,.m4a,.wav,.mp3,.ogg,.opus,.flac" className="sr-only" onChange={(e) => pick(e.target.files?.[0])} />
          {file ? <FileAudio className="size-8 text-primary" aria-hidden /> : <UploadCloud className="size-8 text-muted" aria-hidden />}
          <span className="text-sm font-medium">{file ? file.name : t("Seret file ke sini atau klik untuk memilih")}</span>
          <span className="text-xs text-muted">{file ? `${(file.size / 1048576).toFixed(1)} MB` : t("WAV, MP3, M4A, OGG, FLAC")}</span>
        </label>

        <Field label={t("Judul rapat")}>{(id) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("mis. Rapat mingguan tim")} maxLength={200} />}</Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("Bahasa rekaman")}>{(id) => (
            <Select id={id} value={language} onChange={(e) => setLanguage(e.target.value)}>
              <option value="id">{t("Indonesia")}</option><option value="en">English</option>
            </Select>)}
          </Field>
          <Field label={t("Nama Anda di rekaman")} hint={t("Opsional")}>{(id, d) => <Input id={id} aria-describedby={d} value={me} onChange={(e) => setMe(e.target.value)} maxLength={100} />}</Field>
        </div>

        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" checked={autoProcess && ready} disabled={!ready} onChange={(e) => setAutoProcess(e.target.checked)} className="mt-0.5 size-4 accent-[var(--primary)]" />
          <span>{t("Langsung proses setelah diunggah")}
            {!ready && <span className="block text-xs text-muted">{t("Server ini belum punya mesin pemrosesan; Anda bisa memprosesnya nanti.")}</span>}
          </span>
        </label>

        {progress !== null && <ProgressBar value={Math.round(progress * 100)} label={t("Kemajuan unggahan")} />}
        {error && <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => (busy ? abort.current?.abort() : onOpenChange(false))}>{t("Batal")}</Button>
          <Button type="submit" variant="primary" loading={busy} disabled={!file}>{progress !== null ? t("Mengunggah {pct}%", { pct: Math.round(progress * 100) }) : t("Unggah")}</Button>
        </div>
      </form>
    </Dialog>
  );
}

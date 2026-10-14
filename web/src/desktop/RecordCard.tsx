import { AlertTriangle, CheckCircle2, Circle, Loader2, Mic, Monitor, RotateCcw, Square, Trash2, Upload } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Dialog } from "../components/ui/Dialog";
import { Input } from "../components/ui/Field";
import { ProgressBar } from "../components/ui/Feedback";
import { cn } from "../lib/cn";
import { formatDateTime } from "../lib/format";
import type { Pending, SourceView } from "./types";
import { useRecorder } from "./useRecorder";

export const clock = (secs: number) => {
  const s = Math.floor(secs);
  return `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

const stateLabel: Record<SourceView["state"], string> = {
  recording: "", reconnecting: "Mencoba tersambung lagi", unavailable: "Tidak tersedia", failed: "Terhenti",
};

/** Level meter: the proof, at a glance, that the recording is actually capturing sound.
 *  Colour is never the only cue: there is always text too. */
function Meter({ s }: { s: SourceView }) {
  const Icon = s.source === "mic" ? Mic : Monitor;
  const ok = s.state === "recording";
  const heard = s.level > 0.02;
  return (
    <div className="flex items-center gap-3">
      <Icon className="size-4 shrink-0 text-muted" aria-hidden />
      <div className="w-36 shrink-0 text-sm font-medium">{s.label}</div>
      <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-border" role="meter" aria-label={`Level ${s.label}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(s.level * 100)}>
        <div className={cn("h-full rounded-full transition-[width] duration-150", ok ? "bg-success" : "bg-danger")} style={{ width: `${ok ? Math.round(Math.sqrt(s.level) * 100) : 0}%` }} />
      </div>
      <div className="w-44 shrink-0 text-right text-xs text-muted">
        {ok ? (heard ? "Terdengar" : "Hening") : <span className="font-medium text-danger">{stateLabel[s.state]}</span>}
      </div>
    </div>
  );
}

export function StopDialog({ open, onOpenChange, onStop }: { open: boolean; onOpenChange: (o: boolean) => void; onStop: () => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Hentikan rekaman?" description="Rekaman disimpan dan diunggah untuk diproses. Rapat yang sama tidak bisa dilanjutkan setelah ini.">
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Lanjut merekam</Button>
        <Button variant="primary" autoFocus onClick={() => { onOpenChange(false); onStop(); }}><Square className="size-4" aria-hidden /> Hentikan</Button>
      </div>
    </Dialog>
  );
}

function PendingRow({ p }: { p: Pending }) {
  const { retry, discard } = useRecorder();
  const [confirm, setConfirm] = useState(false);
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-border bg-card px-4 py-3">
      <div className="min-w-0 flex-1 basis-56">
        <p className="truncate font-medium">{p.title}</p>
        <p className="text-xs text-muted">{p.created_unix ? formatDateTime(new Date(p.created_unix * 1000).toISOString()) : "Waktu tidak diketahui"}</p>
      </div>
      {p.crashed && <Badge tone="warning" icon={<AlertTriangle className="size-3" />}>Terhenti mendadak, sudah dipulihkan</Badge>}
      <div className="flex gap-1">
        <Button size="sm" variant="primary" onClick={() => void retry(p.dir).catch((e: Error) => toast.error(e.message))}><Upload className="size-3.5" aria-hidden /> Unggah</Button>
        <Button size="sm" variant="ghost" aria-label={`Hapus rekaman ${p.title}`} onClick={() => setConfirm(true)}><Trash2 className="size-4" aria-hidden /></Button>
      </div>
      <Dialog open={confirm} onOpenChange={setConfirm} title="Hapus rekaman ini?" description="File audio di komputer ini akan dihapus permanen dan tidak bisa dikembalikan.">
        <div className="flex justify-end gap-2">
          <Button variant="ghost" autoFocus onClick={() => setConfirm(false)}>Batal</Button>
          <Button variant="danger" onClick={() => { setConfirm(false); void discard(p.dir).catch((e: Error) => toast.error(e.message)); }}>Hapus permanen</Button>
        </div>
      </Dialog>
    </li>
  );
}

export function RecordCard() {
  const { state, error, start, stop, retry, dismiss } = useRecorder();
  const [title, setTitle] = useState("");
  const [starting, setStarting] = useState(false);
  const [confirmStop, setConfirmStop] = useState(false);

  if (error && !state) return <Card className="p-5 text-sm text-danger" role="alert">{error}</Card>;
  if (!state) return <Card className="h-32 animate-pulse" aria-hidden />;

  const go = async () => {
    setStarting(true);
    try { await start(title.trim() || `Rapat ${formatDateTime(new Date().toISOString())}`); setTitle(""); } catch (e) { toast.error(e instanceof Error ? e.message : "Tidak bisa mulai merekam"); } finally { setStarting(false); }
  };

  return (
    <section aria-label="Perekam" className="flex flex-col gap-4">
      <Card className={cn("p-6", state.phase === "recording" && "border-danger/50")}>
        {state.phase === "recording" && (
          <div className="flex flex-col gap-5" aria-live="polite">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="flex items-center gap-2 font-semibold"><span className="relative flex size-3"><span className="absolute inline-flex size-full animate-ping rounded-full bg-danger opacity-60 motion-reduce:animate-none" /><Circle className="relative size-3 fill-danger text-danger" aria-hidden /></span> Sedang merekam</p>
                <p className="mt-0.5 truncate text-sm text-muted">{state.title}</p>
              </div>
              <p className="text-3xl font-semibold tabular-nums tracking-tight" aria-label="Lama rekaman">{clock(state.elapsed_secs)}</p>
            </div>
            <div className="flex flex-col gap-3">{state.sources.map((s) => <Meter key={s.source} s={s} />)}</div>
            {state.sources.some((s) => s.message && s.state !== "recording") && (
              <ul className="rounded-lg bg-warning-soft px-4 py-3 text-sm text-warning">
                {state.sources.filter((s) => s.message && s.state !== "recording").map((s) => <li key={s.source}><b>{s.label}:</b> {s.message}</li>)}
              </ul>)}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-muted">Aman menutup jendela ini: perekaman terus berjalan dan ikon di baki sistem berwarna merah.</p>
              <Button variant="primary" onClick={() => setConfirmStop(true)}><Square className="size-4" aria-hidden /> Hentikan rekaman</Button>
            </div>
          </div>)}

        {state.phase === "uploading" && state.upload && (
          <div className="flex flex-col gap-3" aria-live="polite">
            <p className="flex items-center gap-2 font-semibold"><Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> Menyimpan dan mengunggah rapat</p>
            <p className="text-sm text-muted">{state.upload.step.charAt(0).toUpperCase() + state.upload.step.slice(1)}… {Math.round(state.upload.fraction * 100)}%</p>
            <ProgressBar value={Math.round(state.upload.fraction * 100)} label="Kemajuan unggahan" />
            <p className="text-xs text-muted">Rekaman sudah aman di komputer ini. Anda boleh mulai pekerjaan lain.</p>
          </div>)}

        {state.phase === "done" && state.last && (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="flex items-center gap-2 font-medium"><CheckCircle2 className="size-5 text-success" aria-hidden /> “{state.last.title}” terunggah{state.last.meeting_id ? " dan sedang diproses" : ""}.</p>
            <div className="flex gap-2">
              {state.last.meeting_id && <Link to={`/rapat/${state.last.meeting_id}`}><Button variant="primary">Buka rapat</Button></Link>}
              <Button variant="ghost" onClick={() => void dismiss()}>Tutup</Button>
            </div>
          </div>)}

        {state.phase === "needs_attention" && state.last && (
          <div className="flex flex-col gap-3" role="alert">
            <p className="flex items-center gap-2 font-semibold text-danger"><AlertTriangle className="size-5" aria-hidden /> Rekaman tersimpan, tetapi belum terunggah</p>
            {state.last.error && <p className="text-sm">{state.last.error}</p>}
            {state.last.warnings.length > 0 && <ul className="list-disc pl-5 text-sm text-warning">{state.last.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => void retry(state.last!.dir).catch((e: Error) => toast.error(e.message))}><RotateCcw className="size-4" aria-hidden /> Coba unggah lagi</Button>
              <Link to="/pengaturan"><Button>Periksa pengaturan server</Button></Link>
              <Button variant="ghost" onClick={() => void dismiss()}>Tutup</Button>
            </div>
          </div>)}

        {state.phase === "idle" && (
          <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); void go(); }}>
            <div className="min-w-60 flex-1">
              <label htmlFor="rec-title" className="mb-1.5 block text-sm font-medium">Rekam rapat sekarang</label>
              <Input id="rec-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Judul rapat (opsional)" maxLength={200} />
            </div>
            <Button type="submit" variant="primary" loading={starting} className="h-10 bg-danger-solid text-danger-solid-fg hover:opacity-90"><Circle className="size-4 fill-current" aria-hidden /> Mulai merekam</Button>
            <p className="basis-full text-xs text-muted">Merekam mikrofon dan suara dari komputer ini. Pastikan peserta rapat tahu bahwa rapat direkam.</p>
          </form>)}
      </Card>

      {state.pending.length > 0 && (
        <section aria-labelledby="pending-h" className="flex flex-col gap-2">
          <h2 id="pending-h" className="text-sm font-semibold">Rekaman yang belum terunggah ({state.pending.length})</h2>
          <ul className="flex flex-col gap-2">{state.pending.map((p) => <PendingRow key={p.dir} p={p} />)}</ul>
        </section>)}

      <StopDialog open={confirmStop} onOpenChange={setConfirmStop} onStop={() => void stop().catch((e: Error) => toast.error(e.message))} />
    </section>
  );
}

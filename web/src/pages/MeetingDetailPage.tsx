import * as Tabs from "@radix-ui/react-tabs";
import {
  ArrowLeft, Check, ClipboardCopy, Download, FileText, HelpCircle, ListChecks, Pencil, Play, RotateCcw, ShieldAlert,
  ShieldCheck, Undo2, Users, X,
} from "lucide-react";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { usePlayer } from "../components/Player";
import { StatusBadge } from "../components/StatusBadge";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Dialog } from "../components/ui/Dialog";
import { EmptyState, ErrorState, ProgressBar, Skeleton } from "../components/ui/Feedback";
import { Field, Input, Select } from "../components/ui/Field";
import { useCapabilities, useInvalidate, useMeeting, usePatchTask, useProcessMeeting } from "../hooks/queries";
import { api, ApiError } from "../lib/api";
import { cn } from "../lib/cn";
import { assigneeName, download, tasksToJson, tasksToMarkdown } from "../lib/export";
import { formatClock, formatDateTime, formatMinutes, percent } from "../lib/format";
import { confidenceLabel, priorityLabel, stageLabel } from "../lib/strings";
import type { MeetingDetail, Participant, Segment, Task } from "../lib/types";

const tones = ["bg-info-soft text-info", "bg-success-soft text-success", "bg-warning-soft text-warning", "bg-primary-soft text-primary", "bg-danger-soft text-danger"];
const speakerName = (p: Participant | undefined) => (p ? p.name ?? p.label : "Tidak diketahui");

/** Which audio file holds this moment: the segment covering it, else the nearest one. */
function sourceAt(segments: Segment[], ms: number): Segment["source"] | null {
  if (!segments.length) return null;
  const hit = segments.find((s) => s.start_ms <= ms && ms <= s.end_ms)
    ?? segments.reduce((a, b) => (Math.abs(b.start_ms - ms) < Math.abs(a.start_ms - ms) ? b : a));
  return hit.source;
}

// ---------------------------------------------------------------- Ringkasan
function SummaryTab({ m }: { m: MeetingDetail }) {
  const s = m.summary;
  if (!s) return <EmptyState icon={<FileText className="size-6" />} title="Belum ada ringkasan">Ringkasan muncul setelah rapat diproses.</EmptyState>;
  return (
    <div className="flex flex-col gap-6">
      {s.overview && <section aria-labelledby="h-ov"><h3 id="h-ov" className="mb-2 font-semibold">Ringkasan</h3><p className="whitespace-pre-line leading-relaxed">{s.overview}</p></section>}
      {s.decisions.length > 0 && (
        <section aria-labelledby="h-dec"><h3 id="h-dec" className="mb-2 font-semibold">Keputusan</h3>
          <ul className="flex flex-col gap-2">{s.decisions.map((d, i) => (
            <li key={i} className="flex gap-2"><Check className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />{d}</li>))}</ul>
        </section>)}
      {s.minutes.length > 0 && (
        <section aria-labelledby="h-min"><h3 id="h-min" className="mb-2 font-semibold">Jalannya rapat</h3>
          <ol className="flex flex-col gap-2 border-l-2 border-border pl-4">{s.minutes.map((p, i) => (
            <li key={i} className="flex gap-3"><span className="w-14 shrink-0 text-sm tabular-nums text-muted">{formatClock(p.start_ms)}</span>{p.point}</li>))}</ol>
        </section>)}
    </div>
  );
}

// --------------------------------------------------------------------- Task
function Confidence({ c }: { c: number }) {
  const Icon = c >= 0.8 ? ShieldCheck : c >= 0.5 ? HelpCircle : ShieldAlert;
  return <Badge tone={c >= 0.8 ? "success" : c >= 0.5 ? "warning" : "danger"} icon={<Icon className="size-3" />}>{confidenceLabel(c)} · {percent(c)}</Badge>;
}

function TaskCard({ t, m, onPatch }: { t: Task; m: MeetingDetail; onPatch: (patch: Parameters<typeof api.patchTask>[1]) => void }) {
  const player = usePlayer();
  const [title, setTitle] = useState(t.title);
  const [est, setEst] = useState(t.estimate_minutes?.toString() ?? "");
  useEffect(() => setTitle(t.title), [t.title]);
  useEffect(() => setEst(t.estimate_minutes?.toString() ?? ""), [t.estimate_minutes]);
  const src = t.evidence_start_ms != null ? sourceAt(m.segments, t.evidence_start_ms) : null;
  const unresolved = !t.assignee_participant_id && t.assignee_name;

  return (
    <Card className="flex flex-col gap-4 p-5">
      <div className="flex items-center gap-3">
        <Input aria-label="Judul task" value={title} onChange={(e) => setTitle(e.target.value)}
          onBlur={() => title.trim().length >= 3 && title !== t.title && onPatch({ title: title.trim() })}
          className="border-transparent bg-transparent px-1 text-base font-semibold hover:border-border focus:border-border" />
        <Confidence c={t.confidence} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="PIC" error={unresolved ? `Disebut “${t.assignee_name}”, belum cocok dengan pembicara` : undefined}>
          {(id, d) => (
            <Select id={id} aria-describedby={d} value={t.assignee_participant_id ?? ""}
              onChange={(e) => onPatch({ assignee_participant_id: e.target.value || null })}>
              <option value="">Belum ditentukan</option>
              {m.participants.map((p) => <option key={p.id} value={p.id}>{speakerName(p)}</option>)}
            </Select>)}
        </Field>
        <Field label="Tenggat" hint={t.deadline_text ? `Diucapkan: “${t.deadline_text}”${t.deadline_approximate ? " · perkiraan" : ""}` : undefined}>
          {(id, d) => <Input id={id} aria-describedby={d} type="date" value={t.deadline ?? ""} onChange={(e) => onPatch({ deadline: e.target.value || null })} />}
        </Field>
        <Field label="Estimasi (menit)" hint={t.estimate_minutes ? formatMinutes(t.estimate_minutes) : undefined}>
          {(id, d) => <Input id={id} aria-describedby={d} type="number" min={1} inputMode="numeric" value={est} onChange={(e) => setEst(e.target.value)}
            onBlur={() => { const n = est ? Number(est) : null; if (n !== t.estimate_minutes && (n === null || n >= 1)) onPatch({ estimate_minutes: n }); }} />}
        </Field>
        <Field label="Prioritas">
          {(id) => <Select id={id} value={t.priority} onChange={(e) => onPatch({ priority: e.target.value as Task["priority"] })}>
            {(["high", "medium", "low"] as const).map((p) => <option key={p} value={p}>{priorityLabel[p]}</option>)}</Select>}
        </Field>
      </div>

      {t.evidence_quote && (
        <blockquote className="flex items-start gap-3 rounded-lg bg-bg px-4 py-3 text-sm">
          <span className="flex-1 italic text-muted">“{t.evidence_quote}”</span>
          {src && t.evidence_start_ms != null && (
            <Button size="sm" variant="secondary" onClick={() => player.play({ meetingId: m.id, source: src, label: t.title }, Math.max(0, t.evidence_start_ms! - 2000))}>
              <Play className="size-3" aria-hidden /> Dengarkan {formatClock(t.evidence_start_ms)}
            </Button>)}
        </blockquote>)}

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => onPatch({ status: "rejected" })}><X className="size-4" aria-hidden /> Tolak</Button>
        <Button variant="primary" onClick={() => onPatch({ status: "confirmed" })}><Check className="size-4" aria-hidden /> Konfirmasi</Button>
      </div>
    </Card>
  );
}

function CompactTask({ t, m, action }: { t: Task; m: MeetingDetail; action: React.ReactNode }) {
  const who = assigneeName(t, m.participants);
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-border bg-card px-4 py-3">
      <span className="min-w-0 flex-1 basis-56 font-medium">{t.title}</span>
      <span className="text-sm text-muted">{[who && `PIC: ${who}`, t.deadline].filter(Boolean).join(" · ")}</span>
      {action}
    </li>
  );
}

function TasksTab({ m }: { m: MeetingDetail }) {
  const patch = usePatchTask(m.id);
  const run = (id: string, p: Parameters<typeof api.patchTask>[1]) =>
    patch.mutate({ id, patch: p }, { onError: (e) => toast.error(e instanceof Error ? e.message : "Gagal menyimpan") });
  const suggested = m.tasks.filter((t) => t.status === "suggested");
  const confirmed = m.tasks.filter((t) => t.status === "confirmed");
  const rejected = m.tasks.filter((t) => t.status === "rejected");
  const sure = suggested.filter((t) => t.confidence >= 0.8);

  if (!m.tasks.length) return <EmptyState icon={<ListChecks className="size-6" />} title="Tidak ada task terdeteksi">Tidak ada pekerjaan yang ditugaskan dalam rapat ini.</EmptyState>;

  return (
    <div className="flex flex-col gap-8">
      {suggested.length > 0 && (
        <section aria-labelledby="h-sug" className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h3 id="h-sug" className="font-semibold">Perlu ditinjau ({suggested.length})</h3>
              <p className="text-sm text-muted">Task ini disarankan AI. Periksa PIC dan tenggatnya sebelum dikonfirmasi.</p></div>
            {sure.length > 0 && <Button onClick={() => sure.forEach((t) => run(t.id, { status: "confirmed" }))}><Check className="size-4" aria-hidden /> Konfirmasi {sure.length} yang yakin</Button>}
          </div>
          {suggested.map((t) => <TaskCard key={t.id} t={t} m={m} onPatch={(p) => run(t.id, p)} />)}
        </section>)}

      {confirmed.length > 0 && (
        <section aria-labelledby="h-conf" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 id="h-conf" className="font-semibold">Dikonfirmasi ({confirmed.length})</h3>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => navigator.clipboard.writeText(tasksToMarkdown(m, confirmed)).then(() => toast.success("Disalin sebagai Markdown"), () => toast.error("Tidak bisa menyalin"))}>
                <ClipboardCopy className="size-3.5" aria-hidden /> Salin Markdown</Button>
              <Button size="sm" onClick={() => download(`task-${m.id.slice(0, 8)}.json`, tasksToJson(m, confirmed), "application/json")}>
                <Download className="size-3.5" aria-hidden /> Unduh JSON</Button>
            </div>
          </div>
          <ul className="flex flex-col gap-2">{confirmed.map((t) => (
            <CompactTask key={t.id} t={t} m={m} action={<Button size="sm" variant="ghost" onClick={() => run(t.id, { status: "suggested" })}><Undo2 className="size-3.5" aria-hidden /> Batalkan</Button>} />))}</ul>
        </section>)}

      {rejected.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer text-sm font-medium text-muted hover:text-fg">Ditolak ({rejected.length})</summary>
          <ul className="mt-3 flex flex-col gap-2">{rejected.map((t) => (
            <CompactTask key={t.id} t={t} m={m} action={<Button size="sm" variant="ghost" onClick={() => run(t.id, { status: "suggested" })}><Undo2 className="size-3.5" aria-hidden /> Kembalikan</Button>} />))}</ul>
        </details>)}
    </div>
  );
}

// ---------------------------------------------------------------- Transkrip
function TranscriptTab({ m }: { m: MeetingDetail }) {
  const player = usePlayer();
  const byId = useMemo(() => new Map(m.participants.map((p, i) => [p.id, { p, tone: tones[i % tones.length]! }])), [m.participants]);
  const groups = useMemo(() => {
    const out: { pid: string | null; segs: Segment[] }[] = [];
    for (const s of m.segments) {
      const last = out[out.length - 1];
      if (last && last.pid === s.participant_id) last.segs.push(s); else out.push({ pid: s.participant_id, segs: [s] });
    }
    return out;
  }, [m.segments]);

  if (!groups.length) return <EmptyState icon={<FileText className="size-6" />} title="Belum ada transkrip">Transkrip muncul setelah rapat diproses.</EmptyState>;
  const live = player.now?.meetingId === m.id ? player : null;

  const row = (g: { pid: string | null; segs: Segment[] }) => {
    const sp = g.pid ? byId.get(g.pid) : undefined;
    const first = g.segs[0]!;
    return (
      <>
        <button onClick={() => player.play({ meetingId: m.id, source: first.source, label: speakerName(sp?.p) }, first.start_ms)}
          className="mt-0.5 h-7 w-[4.5rem] shrink-0 rounded-md text-xs tabular-nums text-muted hover:bg-primary-soft hover:text-primary" aria-label={`Putar dari ${formatClock(first.start_ms)}`}>
          ▶ {formatClock(first.start_ms)}
        </button>
        <div className="min-w-0 flex-1">
          <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-semibold", sp?.tone ?? "bg-border text-muted")}>{speakerName(sp?.p)}</span>
          <p className="mt-1.5 leading-relaxed">
            {g.segs.map((s) => {
              const active = live?.now?.source === s.source && live.ms >= s.start_ms && live.ms <= s.end_ms;
              return <span key={s.id} onClick={() => player.play({ meetingId: m.id, source: s.source, label: speakerName(sp?.p) }, s.start_ms)}
                className={cn("cursor-pointer rounded px-0.5 transition-colors hover:bg-primary-soft", active && "bg-primary-soft text-primary")}>{s.text} </span>;
            })}
          </p>
        </div>
      </>);
  };

  // A multi-hour meeting is thousands of segments (tens of thousands of DOM nodes). Past a threshold only
  // what is on screen is rendered; below it the plain list keeps find-in-page and screen readers complete.
  if (groups.length > VIRTUALIZE_AFTER) return <VirtualTranscript groups={groups} row={row} />;
  return (
    <ol className="flex flex-col gap-5">
      {groups.map((g, i) => <li key={i} className="flex gap-3">{row(g)}</li>)}
    </ol>
  );
}

const VIRTUALIZE_AFTER = 150;

function VirtualTranscript<G>({ groups, row }: { groups: G[]; row: (g: G) => ReactNode }) {
  const listRef = useRef<HTMLOListElement>(null);
  const [margin, setMargin] = useState(0);
  useLayoutEffect(() => { setMargin(listRef.current?.offsetTop ?? 0); }, []);
  const v = useWindowVirtualizer({ count: groups.length, estimateSize: () => 110, overscan: 8, scrollMargin: margin, gap: 20 });
  return (
    <ol ref={listRef} className="relative" style={{ height: v.getTotalSize() }} aria-label={`Transkrip, ${groups.length} bagian`}>
      {v.getVirtualItems().map((it) => (
        <li key={it.key} data-index={it.index} ref={v.measureElement} aria-setsize={groups.length} aria-posinset={it.index + 1}
          className="absolute left-0 top-0 flex w-full gap-3" style={{ transform: `translateY(${it.start - v.options.scrollMargin}px)` }}>
          {row(groups[it.index]!)}
        </li>))}
    </ol>
  );
}

// ---------------------------------------------------------------- Pembicara
function SpeakersTab({ m }: { m: MeetingDetail }) {
  const invalidate = useInvalidate();
  const process = useProcessMeeting();
  const [confirm, setConfirm] = useState(false);
  const ms = (pid: string) => m.segments.filter((s) => s.participant_id === pid).reduce((a, s) => a + (s.end_ms - s.start_ms), 0);
  const save = (p: Participant, name: string) => {
    if ((p.name ?? "") === name.trim()) return;
    api.renameParticipant(p.id, name.trim() || null).then(() => invalidate()).catch((e: Error) => toast.error(e.message));
  };
  if (!m.participants.length) return <EmptyState icon={<Users className="size-6" />} title="Belum ada pembicara">Pembicara dikenali setelah rapat diproses.</EmptyState>;
  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-muted">Beri nama pembicara agar transkrip dan PIC task mudah dibaca.</p>
      <ul className="flex flex-col gap-3">{m.participants.map((p, i) => (
        <li key={p.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
          <span className={cn("grid size-9 place-items-center rounded-full text-xs font-bold", tones[i % tones.length])} aria-hidden>{(p.name ?? p.label).slice(0, 2).toUpperCase()}</span>
          <div className="min-w-48 flex-1">
            <Input aria-label={`Nama untuk ${p.label}`} defaultValue={p.name ?? ""} placeholder={p.is_local_user ? "Nama Anda" : "Beri nama…"}
              onBlur={(e) => save(p, e.target.value)} onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()} />
          </div>
          <span className="text-sm text-muted">{p.is_local_user ? "Mikrofon Anda" : p.label} · berbicara {formatMinutes(Math.max(1, Math.round(ms(p.id) / 60000)))}</span>
        </li>))}</ul>
      <div className="rounded-xl bg-info-soft px-4 py-3 text-sm text-info">
        Task yang menyebut nama pembicara bisa dicocokkan otomatis ke PIC dengan <button className="font-semibold underline" onClick={() => setConfirm(true)}>memproses ulang rapat</button>.
      </div>
      <Dialog open={confirm} onOpenChange={setConfirm} title="Proses ulang rapat?" description="Transkrip, ringkasan, dan task akan dibuat ulang. Nama pembicara tetap dipertahankan.">
        <p className="mb-4 rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">Peninjauan task yang sudah Anda lakukan (konfirmasi, penolakan, suntingan) akan hilang.</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirm(false)}>Batal</Button>
          <Button variant="primary" loading={process.isPending} onClick={() => process.mutate(m.id, { onSuccess: () => setConfirm(false), onError: (e) => toast.error(e.message) })}>Proses ulang</Button>
        </div>
      </Dialog>
    </div>
  );
}

// --------------------------------------------------------------------- Page
function TitleEditor({ m }: { m: MeetingDetail }) {
  const invalidate = useInvalidate();
  const [edit, setEdit] = useState(false);
  const [v, setV] = useState(m.title);
  const commit = () => {
    setEdit(false);
    if (v.trim() && v.trim() !== m.title) api.renameMeeting(m.id, v.trim()).then(() => invalidate()).catch((e: Error) => { setV(m.title); toast.error(e.message); });
  };
  return edit ? (
    <Input autoFocus aria-label="Judul rapat" value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} maxLength={200}
      onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") { setV(m.title); setEdit(false); } }} className="h-11 text-2xl font-semibold" />
  ) : (
    <h1 className="group flex items-center gap-2 text-2xl font-semibold tracking-tight">
      {m.title}
      <button onClick={() => setEdit(true)} aria-label="Ganti judul" className="rounded-lg p-1.5 text-muted opacity-0 hover:bg-primary-soft focus:opacity-100 group-hover:opacity-100"><Pencil className="size-4" /></button>
    </h1>
  );
}

export function MeetingDetailPage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const { data: m, error, isLoading, refetch } = useMeeting(id);
  const caps = useCapabilities();
  const process = useProcessMeeting();
  const tab = params.get("tab") ?? "ringkasan";

  if (isLoading) return <div className="flex flex-col gap-4"><Skeleton className="h-10 w-2/3" /><Skeleton className="h-64" /></div>;
  if (error || !m) return (error instanceof ApiError && error.status === 404)
    ? <Card><EmptyState as="h1" icon={<FileText className="size-6" />} title="Rapat tidak ditemukan" action={<Link to="/"><Button>Kembali ke daftar rapat</Button></Link>}>Rapat ini mungkin sudah dihapus.</EmptyState></Card>
    : <Card><ErrorState error={error} onRetry={() => void refetch()} /></Card>;

  const pending = m.tasks.filter((t) => t.status === "suggested").length;
  const hasResult = m.status === "review" || m.status === "done";
  const stage = m.job?.stage ? stageLabel[m.job.stage] ?? m.job.stage : "Menunggu giliran";
  const canRun = (m.status === "recorded" || m.status === "failed") && (caps.data?.processing_ready ?? false);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to="/" className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted hover:text-fg"><ArrowLeft className="size-4" aria-hidden /> Semua rapat</Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1"><TitleEditor key={m.title} m={m} />
            <p className="mt-1.5 flex flex-wrap items-center gap-3 text-sm text-muted">{formatDateTime(m.started_at)} <StatusBadge status={m.status} /></p></div>
          {canRun && <Button variant="primary" loading={process.isPending} onClick={() => process.mutate(m.id, { onError: (e) => toast.error(e.message) })}>
            {m.status === "failed" ? <RotateCcw className="size-4" aria-hidden /> : <Play className="size-4" aria-hidden />}{m.status === "failed" ? "Coba lagi" : "Proses sekarang"}</Button>}
        </div>
      </div>

      {(m.status === "queued" || m.status === "processing") && (
        <Card className="flex flex-col gap-3 p-6" aria-live="polite">
          <p className="font-medium">{stage}…</p>
          <ProgressBar value={m.job?.progress ?? 0} label="Kemajuan pemrosesan" />
          <p className="text-sm text-muted">Anda boleh menutup halaman ini; pemrosesan tetap berjalan di server.</p>
        </Card>)}
      {m.status === "failed" && <Card className="border-danger/40 bg-danger-soft p-5 text-danger" role="alert"><p className="font-medium">Pemrosesan gagal</p><p className="mt-1 text-sm">{m.error ?? "Terjadi kesalahan yang tidak diketahui."}</p></Card>}
      {m.status === "recorded" && !canRun && <Card className="p-5 text-sm text-muted">Rekaman tersimpan. Server ini belum punya mesin pemrosesan, sambungkan ke server pemrosesan di Pengaturan.</Card>}

      {hasResult && (
        <Tabs.Root value={tab} onValueChange={(v) => setParams((p) => { p.set("tab", v); return p; }, { replace: true })}>
          <Tabs.List aria-label="Bagian rapat" className="mb-6 flex gap-1 overflow-x-auto border-b border-border">
            {[["ringkasan", "Ringkasan"], ["task", "Task"], ["transkrip", "Transkrip"], ["pembicara", "Pembicara"]].map(([v, l]) => (
              <Tabs.Trigger key={v} value={v!} className="-mb-px whitespace-nowrap border-b-2 border-transparent px-4 py-2.5 text-sm font-medium text-muted hover:text-fg data-[state=active]:border-primary data-[state=active]:text-primary">
                {l}{v === "task" && pending > 0 && <span className="ml-2 rounded-full bg-warning-soft px-2 py-0.5 text-xs text-warning">{pending}</span>}
              </Tabs.Trigger>))}
          </Tabs.List>
          <Tabs.Content value="ringkasan"><SummaryTab m={m} /></Tabs.Content>
          <Tabs.Content value="task"><TasksTab m={m} /></Tabs.Content>
          <Tabs.Content value="transkrip"><TranscriptTab m={m} /></Tabs.Content>
          <Tabs.Content value="pembicara"><SpeakersTab m={m} /></Tabs.Content>
        </Tabs.Root>)}
    </div>
  );
}

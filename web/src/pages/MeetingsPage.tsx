import { useQueryClient } from "@tanstack/react-query";
import { FileAudio, Monitor, Play, Plus, RotateCcw, Search, Trash2 } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { isDesktop } from "../desktop/bridge";
import { EngineSetupBanner } from "../desktop/EngineSetupBanner";
import { RecordCard } from "../desktop/RecordCard";
import { StatusBadge } from "../components/StatusBadge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState, ErrorState, ProgressBar, Skeleton } from "../components/ui/Feedback";
import { Input } from "../components/ui/Field";
import { useAuth } from "../hooks/auth";
import { useCapabilities, useMeetings, useProcessMeeting } from "../hooks/queries";
import { api } from "../lib/api";
import { cn } from "../lib/cn";
import { formatDateTime } from "../lib/format";
import { t } from "../lib/i18n";
import { stageLabel } from "../lib/strings";
import type { Meeting } from "../lib/types";

const filters = () => [
  { value: "", label: t("Semua") },
  { value: "review", label: t("Perlu ditinjau") },
  { value: "processing", label: t("Diproses") },
  { value: "done", label: t("Selesai") },
  { value: "failed", label: t("Gagal") },
];

const UploadDialog = lazy(() => import("../components/UploadDialog").then((m) => ({ default: m.UploadDialog })));

function useDebounced<T>(v: T, ms = 250) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

function Row({ m, canProcess, showOwner }: { m: Meeting; canProcess: boolean; showOwner: boolean }) {
  const qc = useQueryClient();
  const process = useProcessMeeting();
  const needsRun = m.status === "recorded" || m.status === "failed";

  async function remove() {
    await api.deleteMeeting(m.id);
    await qc.invalidateQueries({ queryKey: ["meetings"] });
    // Undo instead of "Are you sure?": deleting stays one click, and so does changing your mind.
    toast(t("“{title}” dihapus", { title: m.title }), {
      duration: 10000,
      description: t("Dihapus permanen setelah 30 hari."),
      cancel: { label: t("Hapus permanen"), onClick: () => void api.purgeMeeting(m.id).then(() => toast.success(t("Dihapus permanen."))).catch((e: Error) => toast.error(e.message)) },
      action: { label: t("Urungkan"), onClick: () => void api.restoreMeeting(m.id).then(() => qc.invalidateQueries({ queryKey: ["meetings"] })) },
    });
  }

  return (
    <li>
      <Card className="flex flex-wrap items-center gap-x-4 gap-y-3 p-4 transition-shadow hover:shadow-md">
        <Link to={`/rapat/${m.id}`} className="min-w-0 flex-1 basis-60 rounded-lg outline-offset-4">
          <p className="truncate font-semibold">{m.title}</p>
          <p className="mt-0.5 text-sm text-muted">{formatDateTime(m.started_at)}{showOwner && m.owner_email && <> · <span className="font-medium text-fg">{m.owner_email}</span></>}</p>
          {m.status === "failed" && m.error && <p className="mt-1 line-clamp-2 text-sm text-danger">{m.error}</p>}
        </Link>
        {m.job && (
          <div className="w-48">
            <p className="mb-1 text-xs text-muted">{m.job.stage ? stageLabel[m.job.stage] ?? m.job.stage : t("Menunggu giliran")}</p>
            <ProgressBar value={m.job.progress} label={t("Kemajuan pemrosesan {title}", { title: m.title })} />
          </div>
        )}
        <StatusBadge status={m.status} />
        <div className="flex gap-1">
          {needsRun && canProcess && (
            <Button size="sm" variant="primary" loading={process.isPending}
              onClick={() => process.mutate(m.id, { onError: (e) => toast.error(e.message) })}>
              {m.status === "failed" ? <RotateCcw className="size-3.5" aria-hidden /> : <Play className="size-3.5" aria-hidden />}
              {m.status === "failed" ? t("Coba lagi") : t("Proses")}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => void remove().catch((e: Error) => toast.error(e.message))} aria-label={t("Hapus {title}", { title: m.title })}>
            <Trash2 className="size-4" aria-hidden />
          </Button>
        </div>
      </Card>
    </li>
  );
}

export function MeetingsPage() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const [text, setText] = useState(params.get("q") ?? "");
  const q = useDebounced(text);
  const [upload, setUpload] = useState(false);
  const nav = useNavigate();
  const search = useRef<HTMLInputElement>(null);
  const { canAdmin } = useAuth();
  const scope = canAdmin && params.get("scope") === "all" ? "all" : "mine";
  const { data, error, isLoading, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } = useMeetings(q, status, scope);
  const caps = useCapabilities();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(el.tagName)) { e.preventDefault(); search.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const setStatus = (v: string) => setParams((p) => { v ? p.set("status", v) : p.delete("status"); return p; }, { replace: true });
  const setScope = (v: string) => setParams((p) => { v === "all" ? p.set("scope", "all") : p.delete("scope"); return p; }, { replace: true });
  const filtering = Boolean(q || status);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("Rapat")}</h1>
          <p className="mt-1 text-sm text-muted">{t("Semua rekaman, transkrip, dan task Anda di satu tempat.")}</p>
        </div>
        <Button variant="primary" onClick={() => setUpload(true)}><Plus className="size-4" aria-hidden /> {t("Rapat baru")}</Button>
      </div>

      {isDesktop() && <RecordCard />}
      {isDesktop() && <EngineSetupBanner ready={caps.data?.processing_ready} />}

      {canAdmin && (
        <div role="group" aria-label={t("Cakupan rapat")} className="flex w-fit gap-1 rounded-lg border border-border bg-card p-1">
          {([["mine", t("Milik saya")], ["all", t("Semua pengguna")]] as const).map(([v, l]) => (
            <button key={v} onClick={() => setScope(v)} aria-pressed={scope === v}
              className={cn("rounded-md px-3 py-1.5 text-sm font-medium transition-colors", scope === v ? "bg-primary text-primary-fg" : "text-muted hover:text-fg")}>{l}</button>))}
        </div>)}

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-60 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
          <Input ref={search} aria-label={t("Cari rapat")} placeholder={t("Cari rapat…  (tekan /)")} className="pl-9"
            value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <div role="group" aria-label={t("Saring status")} className="flex flex-wrap gap-1.5">
          {filters().map((f) => (
            <button key={f.value} onClick={() => setStatus(f.value)} aria-pressed={status === f.value}
              className={cn("rounded-full px-3 py-1.5 text-sm font-medium transition-colors",
                status === f.value ? "bg-primary text-primary-fg" : "bg-card text-muted border border-border hover:text-fg")}>
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-3" aria-label={t("Memuat daftar rapat")}>{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[76px]" />)}</div>
      ) : error ? (
        <Card><ErrorState error={error} onRetry={() => void refetch()} /></Card>
      ) : data && data.length === 0 ? (
        <Card>
          {filtering ? (
            <EmptyState icon={<Search className="size-6" />} title={t("Tidak ada rapat yang cocok")}
              action={<Button onClick={() => { setText(""); setStatus(""); }}>{t("Hapus pencarian")}</Button>}>
              {t("Coba kata kunci lain atau tampilkan semua status.")}
            </EmptyState>
          ) : (
            <EmptyState icon={<FileAudio className="size-6" />} title={t("Belum ada rapat")}
              action={<Button variant="primary" onClick={() => setUpload(true)}><Plus className="size-4" aria-hidden /> {t("Unggah rekaman")}</Button>}>
              {t("Unggah rekaman rapat dan Rekamind akan membuat transkrip per pembicara, ringkasan, serta daftar task lengkap dengan PIC dan tenggat.")}
              {!isDesktop() && <span className="mt-3 flex items-center justify-center gap-1.5 text-xs"><Monitor className="size-3.5" aria-hidden /> {t("Merekam langsung tersedia di aplikasi desktop.")}</span>}
            </EmptyState>
          )}
        </Card>
      ) : (
        <>
          <ul className="flex flex-col gap-3">{data?.map((m) => <Row key={m.id} m={m} canProcess={caps.data?.processing_ready ?? false} showOwner={scope === "all"} />)}</ul>
          {hasNextPage && <Button className="self-center" loading={isFetchingNextPage} onClick={() => void fetchNextPage()}>{t("Tampilkan lebih banyak")}</Button>}
        </>
      )}

      {upload && <Suspense fallback={null}><UploadDialog open={upload} onOpenChange={setUpload} onCreated={(id) => nav(`/rapat/${id}`)} /></Suspense>}
    </div>
  );
}

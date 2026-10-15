import { ChevronDown, Cpu, Download, Loader2, ShieldCheck, Zap } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { ProgressBar } from "../components/ui/Feedback";
import { useBackendReady } from "./backend";
import { desktop } from "./bridge";
import { Input } from "../components/ui/Field";
import type { EngineCheck, EngineState, SettingsView } from "./types";
import { t } from "../lib/i18n";

const KIND_LABEL = { cpu: "CPU", cuda: "NVIDIA GPU", openvino: "Intel GPU", vulkan: "GPU (Vulkan)" } as const;

export interface InstallProgress { pct: number | null; doneMb: number; totalMb: number | null; speed: number | null; stalled: boolean }

const num = (v: string) => Number(v.replace(/,/g, ""));
/** The installer prints a structured line every few seconds ("... 123 / 700 MB (17%), 0.45 MB/s"), and a warning when a
 *  download stands still. The newest one of those is the progress; the rest of the log is for diagnosis. */
export function parseInstallProgress(lines: string[]): InstallProgress | null {
  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i]!;
    if (/Tidak ada kemajuan unduhan/.test(l)) return { pct: null, doneMb: 0, totalMb: null, speed: null, stalled: true };
    const a = /\.\.\. ([\d.,]+) \/ ([\d.,]+) MB \((\d+)%\), ([\d.]+) MB\/s/.exec(l);
    if (a) return { pct: Number(a[3]), doneMb: num(a[1]!), totalMb: num(a[2]!), speed: Number(a[4]), stalled: false };
    const b = /\.\.\. ([\d.,]+) MB(?: terunduh)?(?:, ([\d.]+) MB\/s)?/.exec(l);
    if (b) return { pct: null, doneMb: num(b[1]!), totalMb: null, speed: b[2] ? Number(b[2]) : null, stalled: false };
  }
  return null;
}

/** Installs and verifies the speech engines. They are not in the installer: they are several GB and
 *  depend on the hardware, so the user picks once and sees real progress. */
export function EnginesPanel({ recording, whisperModel, hasHfToken = false, onTokenSaved }:
  { recording: boolean; whisperModel: string; hasHfToken?: boolean; onTokenSaved?: (v: SettingsView) => void }) {
  const [state, setState] = useState<EngineState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [diarize, setDiarize] = useState(true);
  const [check, setCheck] = useState<EngineCheck | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [showLog, setShowLog] = useState(false);
  const [token, setToken] = useState("");
  const [savingToken, setSavingToken] = useState(false);
  const logRef = useRef<HTMLPreElement>(null);
  const { retry } = useBackendReady();
  const retryRef = useRef(retry);
  retryRef.current = retry;

  const refresh = useCallback(() => {
    desktop.engines().then((s) => { setState(s); setLines(s.job.log.slice(-12)); setError(null); }).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  // Live output. Window destroyed + reopened mid-install? `refresh` replays the buffered log.
  useEffect(() => {
    let off2: (() => void) | undefined; let dead = false;
    void import("@tauri-apps/api/event").then(({ listen }) => Promise.all([
      listen<string>("engines://line", (e) => setLines((p) => [...p.slice(-11), e.payload])),
      listen<string | null>("engines://done", (e) => {
        refresh();
        retryRef.current(); // the local backend was stopped for the install; bring it back
        if (e.payload) toast.error(t("Pemasangan gagal: {err}", { err: e.payload })); else { toast.success(t("Pemasangan selesai.")); void desktop.checkEngines().then(setCheck).catch(() => undefined); }
      }),
    ])).then(([a, b]) => { off2 = () => { a(); b(); }; if (dead) off2(); }).catch(() => undefined);
    return () => { dead = true; off2?.(); };
  }, [refresh]);
  useEffect(() => { const el = logRef.current; if (el) el.scrollTop = el.scrollHeight; }, [lines]);

  const running = state?.job.running ?? null;
  const progress = running ? parseInstallProgress(lines) : null;
  const failed = !running && !!state?.job.last_error;
  // Speaker separation is on by default; it cannot work without a Hugging Face token, so installing with it is blocked
  // until the token is saved (or the user explicitly opts out) instead of failing later as "one speaker".
  const needsToken = diarize && !hasHfToken;
  const blocked = recording || needsToken;
  const saveToken = () => {
    setSavingToken(true); setError(null);
    desktop.setSecrets({ hfToken: token.trim() })
      .then((v) => { setToken(""); onTokenSaved?.(v); toast.success(t("Token Hugging Face tersimpan.")); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setSavingToken(false));
  };
  const act = (fn: () => Promise<unknown>) => { setError(null); fn().then(refresh).catch((e: Error) => setError(e.message)); };
  const pack = state?.pack;
  const installed = !!pack?.asr;
  const hasIntel = !!pack?.gpus?.some((g) => g.vendor === "intel");
  const hasNvidia = !!pack?.gpus?.some((g) => g.vendor === "nvidia");
  const hasAmd = !!pack?.gpus?.some((g) => g.vendor === "amd");

  return (
    <section aria-labelledby="engines-h" className="flex flex-col gap-4 rounded-lg border border-border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Cpu className="size-4 text-primary" aria-hidden />
        <h3 id="engines-h" className="font-semibold">{t("Mesin transkripsi")}</h3>
        {installed
          ? <Badge tone="success">{pack?.kind ? t("Terpasang · {kind}", { kind: KIND_LABEL[pack.kind] }) : t("Terpasang")}</Badge>
          : <Badge tone="warning">{t("Belum dipasang")}</Badge>}
        {pack?.diarize && <Badge tone="neutral">{t("Pemisah pembicara")}</Badge>}
      </div>
      <p className="text-sm text-muted">
        {installed
          ? t("Transkripsi berjalan di komputer ini. Model suara diunduh sekali, saat pertama dipakai (atau tombol di bawah).")
          : t("Pemasangan mengunduh beberapa GB (lebih besar untuk NVIDIA). Hanya perlu sekali. Rekaman tetap bisa dilakukan tanpa ini.")}
      </p>

      {!running && hasIntel && !hasNvidia && !installed && (
        <p className="text-sm">{t("GPU Intel terdeteksi di komputer ini. Pilih “Pasang untuk Intel GPU” agar transkripsi lebih cepat dari CPU (eksperimental).")}</p>
      )}
      {!running && hasAmd && !hasNvidia && !installed && (
        <p className="text-sm">{t("GPU AMD terdeteksi di komputer ini. Pilih “Pasang untuk GPU AMD (Vulkan)” agar transkripsi lebih cepat dari CPU (eksperimental).")}</p>
      )}
      {!running && (
        <>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]" checked={diarize} onChange={(e) => setDiarize(e.target.checked)} />
            <span>{t("Sertakan pemisah pembicara (pyannote, tambahan ± beberapa GB; perlu token Hugging Face)")}</span></label>
          {needsToken && (
            <div role="alert" className="flex flex-col gap-3 rounded-xl border border-warning/40 bg-warning-soft p-4 text-sm">
              <p className="font-semibold text-warning">{t("Token Hugging Face wajib diisi untuk memasang pemisah pembicara.")}</p>
              <ol className="flex list-decimal flex-col gap-1.5 pl-5">
                <li>{t("Buat token (tipe Read) di huggingface.co/settings/tokens.")}</li>
                <li>{t("Buka halaman model pyannote/speaker-diarization-3.1 dan pyannote/segmentation-3.0 di Hugging Face, lalu setujui syaratnya.")}</li>
                <li>{t("Tempel token di sini, lalu simpan:")}</li>
              </ol>
              <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (token.trim()) saveToken(); }}>
                <Input aria-label={t("Tempel token Hugging Face")} type="password" autoComplete="off" placeholder="hf_…" value={token}
                  onChange={(e) => setToken(e.target.value)} className="min-w-60 flex-1" />
                <Button type="submit" variant="primary" loading={savingToken} disabled={!token.trim()}>{t("Simpan token")}</Button>
              </form>
              <p className="text-muted">{t("Tidak memerlukan pemisah pembicara? Hilangkan centang di atas untuk memasang mesin tanpanya.")}</p>
            </div>)}
          <div className="flex flex-wrap gap-2">
            <Button variant={installed ? "secondary" : "primary"} disabled={blocked} onClick={() => act(() => desktop.installEngines("cpu", diarize))}><Download className="size-4" aria-hidden /> {installed ? t("Pasang ulang untuk CPU") : t("Pasang untuk CPU")}</Button>
            <Button variant="secondary" disabled={blocked} onClick={() => act(() => desktop.installEngines("cuda", diarize))}><Zap className="size-4" aria-hidden /> {installed ? t("Pasang ulang untuk NVIDIA GPU") : t("Pasang untuk NVIDIA GPU")}</Button>
            <Button variant="secondary" disabled={blocked} onClick={() => act(() => desktop.installEngines("vulkan", diarize))}><Zap className="size-4" aria-hidden /> {installed ? t("Pasang ulang untuk GPU AMD (Vulkan)") : t("Pasang untuk GPU AMD (Vulkan)")}</Button>
            <Button variant="secondary" disabled={blocked} onClick={() => act(() => desktop.installEngines("openvino", diarize))}><Zap className="size-4" aria-hidden /> {installed ? t("Pasang ulang untuk Intel GPU") : t("Pasang untuk Intel GPU")}</Button>
            {installed && <Button variant="ghost" onClick={() => act(() => desktop.warmupModel())}>{t("Unduh model {model} sekarang", { model: whisperModel })}</Button>}
            {installed && <Button variant="ghost" onClick={() => { setCheck(null); desktop.checkEngines().then(setCheck).catch((e: Error) => setError(e.message)); }}><ShieldCheck className="size-4" aria-hidden /> {t("Uji mesin")}</Button>}
          </div>
        </>
      )}

      {running && (
        <div className="flex flex-col gap-2">
          <p role="status" className="flex items-center gap-2 text-sm font-medium"><Loader2 className="size-4 animate-spin" aria-hidden /> {running.startsWith("install") ? t("Memasang mesin…") : t("Mengunduh model…")}</p>
          {progress?.pct != null
            ? <ProgressBar value={progress.pct} label={t("Kemajuan unduhan")} />
            : <div role="progressbar" aria-label={t("Kemajuan unduhan")} className="h-1.5 w-full overflow-hidden rounded-full bg-border"><div className="h-full w-1/3 animate-pulse rounded-full bg-primary motion-reduce:animate-none" /></div>}
          <p className="text-xs text-muted">
            {progress?.totalMb != null
              ? t("Unduhan saat ini: {done} dari {total} MB{speed}", { done: Math.round(progress.doneMb), total: Math.round(progress.totalMb), speed: progress.speed != null ? ` · ${progress.speed.toFixed(2)} MB/s` : "" })
              : progress && !progress.stalled
              ? t("Unduhan saat ini: {done} MB{speed}", { done: Math.round(progress.doneMb), speed: progress.speed != null ? ` · ${progress.speed.toFixed(2)} MB/s` : "" })
              : t("Menyiapkan paket… pemasangan beberapa GB bisa memakan waktu lama.")}
          </p>
          {progress?.stalled && <p role="status" className="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">{t("Unduhan hampir tidak bergerak: jaringan ke server paket sedang lambat. Pemasangan masih mencoba; Anda bisa menunggu atau membatalkan.")}</p>}
          <Button variant="ghost" size="sm" className="self-start" onClick={() => act(() => desktop.cancelEngines())}>{t("Batalkan")}</Button>
        </div>
      )}

      {lines.length > 0 && (
        <button type="button" aria-expanded={showLog || failed} onClick={() => setShowLog((v) => !v)}
          className="flex items-center gap-1 self-start text-xs font-medium text-muted hover:text-fg">
          <ChevronDown className={`size-3.5 transition-transform ${showLog || failed ? "rotate-180" : ""}`} aria-hidden /> {showLog || failed ? t("Sembunyikan log") : t("Tampilkan log")}
        </button>
      )}
      {lines.length > 0 && (showLog || failed) && (
        <pre ref={logRef} tabIndex={0} aria-label={t("Keluaran pemasangan")} className="max-h-40 overflow-auto rounded-lg bg-bg p-3 text-xs leading-relaxed text-muted">{lines.join("\n")}</pre>
      )}

      {check && (
        check.ok
          ? check.vulkan_devices
            ? <p role="status" className="text-sm text-success">{t("Mesin berfungsi (whisper.cpp {version}).", { version: check.whispercpp ?? "" })} {check.model_cached === null ? t("Program terpasang; unduh model dulu agar GPU bisa dipastikan.") : check.gpu ? t("GPU terdeteksi: {name}.", { name: (check.vulkan_devices ?? []).join(", ") }) : t("Tidak ada perangkat Vulkan; memakai CPU (lebih lambat).")}</p>
            : check.openvino
            ? <p role="status" className="text-sm text-success">{t("Mesin berfungsi (OpenVINO {version}).", { version: check.openvino })} {check.intel_gpu ? t("GPU Intel terdeteksi.") : t("GPU Intel tidak terdeteksi; memakai CPU (lebih lambat).")} <span className="text-muted">{t("Perangkat: {list}", { list: (check.ov_devices ?? []).join(", ") })}</span></p>
            : <p role="status" className="text-sm text-success">{t("Mesin berfungsi (faster-whisper {version}).", { version: check.faster_whisper ?? "" })} {check.cuda_devices > 0 ? t("GPU NVIDIA terdeteksi: {n}.", { n: check.cuda_devices }) : t("GPU NVIDIA tidak terdeteksi; memakai CPU (lebih lambat).")}</p>
          : <p role="alert" className="text-sm text-danger">{t("Mesin terpasang tetapi tidak bisa dimuat: {err}", { err: check.error ?? "" })}</p>
      )}
      {state?.job.last_error && !running && <p role="alert" className="text-sm text-danger">{t("Pemasangan terakhir gagal: {err}", { err: state.job.last_error ?? "" })}</p>}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {pack?.build && <p className="text-xs text-muted">{t("Build: {build}", { build: pack.build })}</p>}
      <p className="text-xs text-muted">{t("Lokasi:")} <code className="rounded bg-bg px-1.5 py-0.5">{pack?.pack_dir ?? "…"}</code></p>
    </section>
  );
}

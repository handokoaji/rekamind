import { Cpu, Download, Loader2, ShieldCheck, Zap } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { useBackendReady } from "./backend";
import { desktop } from "./bridge";
import type { EngineCheck, EngineState } from "./types";
import { t } from "../lib/i18n";

const KIND_LABEL = { cpu: "CPU", cuda: "NVIDIA GPU", openvino: "Intel GPU" } as const;

/** Installs and verifies the speech engines. They are not in the installer: they are several GB and
 *  depend on the hardware, so the user picks once and sees real progress. */
export function EnginesPanel({ recording, whisperModel }: { recording: boolean; whisperModel: string }) {
  const [state, setState] = useState<EngineState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [diarize, setDiarize] = useState(false);
  const [check, setCheck] = useState<EngineCheck | null>(null);
  const [lines, setLines] = useState<string[]>([]);
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
  const act = (fn: () => Promise<unknown>) => { setError(null); fn().then(refresh).catch((e: Error) => setError(e.message)); };
  const pack = state?.pack;
  const installed = !!pack?.asr;
  const hasIntel = !!pack?.gpus?.some((g) => g.vendor === "intel");
  const hasNvidia = !!pack?.gpus?.some((g) => g.vendor === "nvidia");

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
      {!running && (
        <>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]" checked={diarize} onChange={(e) => setDiarize(e.target.checked)} />
            <span>{t("Sertakan pemisah pembicara (pyannote, tambahan ± beberapa GB; perlu token Hugging Face)")}</span></label>
          <div className="flex flex-wrap gap-2">
            <Button variant={installed ? "secondary" : "primary"} disabled={recording} onClick={() => act(() => desktop.installEngines("cpu", diarize))}><Download className="size-4" aria-hidden /> {installed ? t("Pasang ulang untuk CPU") : t("Pasang untuk CPU")}</Button>
            <Button variant="secondary" disabled={recording} onClick={() => act(() => desktop.installEngines("cuda", diarize))}><Zap className="size-4" aria-hidden /> {installed ? t("Pasang ulang untuk NVIDIA GPU") : t("Pasang untuk NVIDIA GPU")}</Button>
            <Button variant="secondary" disabled={recording} onClick={() => act(() => desktop.installEngines("openvino", diarize))}><Zap className="size-4" aria-hidden /> {installed ? t("Pasang ulang untuk Intel GPU") : t("Pasang untuk Intel GPU")}</Button>
            {installed && <Button variant="ghost" onClick={() => act(() => desktop.warmupModel())}>{t("Unduh model {model} sekarang", { model: whisperModel })}</Button>}
            {installed && <Button variant="ghost" onClick={() => { setCheck(null); desktop.checkEngines().then(setCheck).catch((e: Error) => setError(e.message)); }}><ShieldCheck className="size-4" aria-hidden /> {t("Uji mesin")}</Button>}
          </div>
        </>
      )}

      {running && (
        <div className="flex flex-col gap-2">
          <p role="status" className="flex items-center gap-2 text-sm font-medium"><Loader2 className="size-4 animate-spin" aria-hidden /> {running.startsWith("install") ? t("Memasang mesin…") : t("Mengunduh model…")}</p>
          <Button variant="ghost" size="sm" className="self-start" onClick={() => act(() => desktop.cancelEngines())}>{t("Batalkan")}</Button>
        </div>
      )}

      {lines.length > 0 && (
        <pre ref={logRef} tabIndex={0} aria-label={t("Keluaran pemasangan")} className="max-h-40 overflow-auto rounded-lg bg-bg p-3 text-xs leading-relaxed text-muted">{lines.join("\n")}</pre>
      )}

      {check && (
        check.ok
          ? check.openvino
            ? <p role="status" className="text-sm text-success">{t("Mesin berfungsi (OpenVINO {version}).", { version: check.openvino })} {check.intel_gpu ? t("GPU Intel terdeteksi.") : t("GPU Intel tidak terdeteksi; memakai CPU (lebih lambat).")} <span className="text-muted">{t("Perangkat: {list}", { list: (check.ov_devices ?? []).join(", ") })}</span></p>
            : <p role="status" className="text-sm text-success">{t("Mesin berfungsi (faster-whisper {version}).", { version: check.faster_whisper ?? "" })} {check.cuda_devices > 0 ? t("GPU NVIDIA terdeteksi: {n}.", { n: check.cuda_devices }) : t("GPU NVIDIA tidak terdeteksi; memakai CPU (lebih lambat).")}</p>
          : <p role="alert" className="text-sm text-danger">{t("Mesin terpasang tetapi tidak bisa dimuat: {err}", { err: check.error ?? "" })}</p>
      )}
      {state?.job.last_error && !running && <p role="alert" className="text-sm text-danger">{t("Pemasangan terakhir gagal: {err}", { err: state.job.last_error ?? "" })}</p>}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <p className="text-xs text-muted">{t("Lokasi:")} <code className="rounded bg-bg px-1.5 py-0.5">{pack?.pack_dir ?? "…"}</code></p>
    </section>
  );
}

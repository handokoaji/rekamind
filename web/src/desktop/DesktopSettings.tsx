import { Keyboard, Monitor } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Field, Input, Select } from "../components/ui/Field";
import { desktop } from "./bridge";
import type { DesktopSettings as S, SettingsView } from "./types";
import { EnginesPanel } from "./EnginesPanel";
import { useRecorder } from "./useRecorder";

export function DesktopSettings() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [s, setS] = useState<S | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  // Secrets are write-only: the shell never sends them back, so the box is empty unless being changed.
  const [llmKey, setLlmKey] = useState("");
  const [hfToken, setHfToken] = useState("");
  const { state } = useRecorder();
  const recording = state?.phase === "recording";

  useEffect(() => { void desktop.settings().then((v) => { setView(v); setS(v.settings); }).catch((e: Error) => setError(e.message)); }, []);
  if (!s || !view) return <Card className="h-40 animate-pulse" aria-hidden />;
  const set = <K extends keyof S>(k: K, v: S[K]) => setS((p) => (p ? { ...p, [k]: v } : p));

  async function save() {
    if (!s) return;
    setSaving(true); setError(undefined);
    try {
      let next = await desktop.saveSettings(s);
      if (llmKey || hfToken) {
        next = await desktop.setSecrets({ ...(llmKey ? { llmApiKey: llmKey } : {}), ...(hfToken ? { hfToken } : {}) });
        setLlmKey(""); setHfToken("");
      }
      setView(next); setS(next.settings);
      toast.success("Pengaturan disimpan.");
    } catch (e) { setError(e instanceof Error ? e.message : "Gagal menyimpan"); } finally { setSaving(false); }
  }

  return (
    <Card className="flex flex-col gap-5 p-6">
      <div className="flex items-center gap-2"><Monitor className="size-4 text-primary" aria-hidden /><h2 className="font-semibold">Aplikasi desktop</h2></div>

      <Field label="Tempat pemrosesan" hint={s.mode === "local" ? "Mesin pemrosesan dinyalakan di komputer ini hanya setelah rapat selesai, lalu dimatikan lagi." : "Rekaman dikirim ke server lain; komputer ini hanya merekam."}>
        {(id, d) => <Select id={id} aria-describedby={d} value={s.mode} onChange={(e) => set("mode", e.target.value as S["mode"])}>
          <option value="local">Komputer ini (GPU lokal)</option><option value="remote">Server terpisah</option></Select>}
      </Field>

      {s.mode === "remote" ? (
        <Field label="Alamat server" hint="Server harus mengizinkan asal aplikasi ini (REKAMIND_CORS_ORIGINS)." error={error?.includes("Alamat server") ? error : undefined}>
          {(id, d) => <Input id={id} aria-describedby={d} value={s.server} onChange={(e) => set("server", e.target.value)} placeholder="https://rekamind.kantor.id" inputMode="url" />}
        </Field>
      ) : (
        <details className="rounded-lg border border-border px-4 py-3 text-sm">
          <summary className="cursor-pointer font-medium">Lanjutan: cara menyalakan mesin lokal</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Field label="Program" hint={view.bundled_backend ? "“auto” memakai mesin bawaan aplikasi." : "“auto” memakai `python -m rekamind_server` (aplikasi ini tidak membawa mesin bawaan)."}>{(id, d) => <Input id={id} aria-describedby={d} value={s.local_program} onChange={(e) => set("local_program", e.target.value)} />}</Field>
            <Field label="Port">{(id) => <Input id={id} type="number" min={1024} max={65535} value={s.local_port} onChange={(e) => set("local_port", Number(e.target.value))} />}</Field>
            <div className="sm:col-span-2"><Field label="Argumen (satu per baris)">{(id) => <textarea id={id} rows={2} className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm" value={s.local_args.join("\n")} onChange={(e) => set("local_args", e.target.value.split("\n").filter(Boolean))} />}</Field></div>
          </div>
        </details>
      )}

      {s.mode === "local" && (
        <>
          <EnginesPanel recording={recording} whisperModel={s.whisper_model} />
          <fieldset className="flex flex-col gap-4 rounded-lg border border-border p-4">
            <legend className="px-1 text-sm font-semibold">Pemrosesan di komputer ini</legend>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Model Whisper" hint="large-v3 paling akurat; medium/small lebih cepat dan hemat memori.">{(id, d) => <Select id={id} aria-describedby={d} value={s.whisper_model} onChange={(e) => set("whisper_model", e.target.value)}>
                {["large-v3", "large-v3-turbo", "medium", "small", "base"].map((m) => <option key={m} value={m}>{m}</option>)}
                {!["large-v3", "large-v3-turbo", "medium", "small", "base"].includes(s.whisper_model) && <option value={s.whisper_model}>{s.whisper_model}</option>}</Select>}</Field>
              <Field label="Perangkat">{(id) => <Select id={id} value={s.whisper_device} onChange={(e) => set("whisper_device", e.target.value as S["whisper_device"])}><option value="auto">Otomatis (GPU bila ada)</option><option value="cuda">NVIDIA GPU</option><option value="cpu">CPU</option></Select>}</Field>
              <Field label="Pemisah pembicara" hint="“Tanpa” menandai suara komputer sebagai satu pembicara.">{(id, d) => <Select id={id} aria-describedby={d} value={s.diarizer} onChange={(e) => set("diarizer", e.target.value as S["diarizer"])}><option value="none">Tanpa</option><option value="pyannote">pyannote (perlu paket + token)</option></Select>}</Field>
              <Field label="Token Hugging Face" hint={view.has_hf_token ? "Sudah tersimpan. Isi untuk menggantinya." : "Hanya untuk pyannote."}>{(id, d) => <Input id={id} aria-describedby={d} type="password" autoComplete="off" value={hfToken} placeholder={view.has_hf_token ? "••••••••" : ""} onChange={(e) => setHfToken(e.target.value)} />}</Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Layanan ringkasan (OpenAI-compatible)" hint="Ringkasan dan task ditulis oleh LLM. Contoh: Groq, OpenAI, atau Ollama lokal.">{(id, d) => <Input id={id} aria-describedby={d} value={s.llm_base_url} onChange={(e) => set("llm_base_url", e.target.value)} inputMode="url" />}</Field>
              <Field label="Model ringkasan">{(id) => <Input id={id} value={s.llm_model} onChange={(e) => set("llm_model", e.target.value)} />}</Field>
              <Field label="Kunci API ringkasan" hint={view.has_llm_key ? "Sudah tersimpan di penyimpanan kredensial sistem. Isi untuk menggantinya." : "Disimpan di penyimpanan kredensial sistem, bukan di file pengaturan."}>{(id, d) => <Input id={id} aria-describedby={d} type="password" autoComplete="off" value={llmKey} placeholder={view.has_llm_key ? "••••••••" : ""} onChange={(e) => setLlmKey(e.target.value)} />}</Field>
              <Field label="Istilah khusus" hint="Nama orang, singkatan, atau jargon (pisahkan dengan koma) agar lebih tepat ditranskripsi.">{(id, d) => <Input id={id} aria-describedby={d} value={s.glossary} onChange={(e) => set("glossary", e.target.value)} />}</Field>
            </div>
          </fieldset>
        </>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Nama Anda di rekaman" hint="Dipakai untuk mengenali suara mikrofon sebagai Anda.">{(id, d) => <Input id={id} aria-describedby={d} value={s.local_user_name} onChange={(e) => set("local_user_name", e.target.value)} maxLength={100} />}</Field>
        <Field label="Bahasa rapat">{(id) => <Select id={id} value={s.language} onChange={(e) => set("language", e.target.value as S["language"])}><option value="id">Indonesia</option><option value="en">English</option></Select>}</Field>
      </div>

      <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]" checked={s.auto_process} onChange={(e) => set("auto_process", e.target.checked)} />
        <span>Langsung proses setelah rekaman diunggah</span></label>

      <Field label="Pintasan keyboard mulai/berhenti merekam" hint={view.hotkey_error ?? "Berlaku dari aplikasi mana pun. Contoh: CmdOrCtrl+Alt+R"} error={view.hotkey_error ?? undefined}>
        {(id, d) => <div className="relative"><Keyboard className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden /><Input id={id} aria-describedby={d} className="pl-9" value={s.hotkey} onChange={(e) => set("hotkey", e.target.value)} /></div>}
      </Field>

      <p className="text-xs text-muted">Rekaman disimpan di <code className="rounded bg-bg px-1.5 py-0.5">{view.recordings_dir}</code></p>
      {error && !error.includes("Alamat server") && <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
      <div className="flex items-center gap-3">
        <Button variant="primary" loading={saving} disabled={recording} onClick={() => void save()}>Simpan</Button>
        {recording && <span className="text-sm text-muted">Hentikan rekaman dulu untuk mengubah pengaturan.</span>}
      </div>
    </Card>
  );
}

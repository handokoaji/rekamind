import { CheckCircle2, Server, XCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { isDesktop } from "../desktop/bridge";
import { DesktopSettings } from "../desktop/DesktopSettings";
import { Field, Input } from "../components/ui/Field";
import { useCapabilities, useHealth } from "../hooks/queries";
import { getBackendUrl, normalizeBackendUrl, setBackendUrl } from "../lib/api";

export function SettingsPage() {
  const [url, setUrl] = useState(getBackendUrl());
  const [testing, setTesting] = useState(false);
  const health = useHealth();
  const caps = useCapabilities();
  const normalized = normalizeBackendUrl(url);
  const invalid = normalized === null;

  async function test() {
    if (invalid) return;
    setTesting(true);
    try {
      const r = await fetch(`${normalized}/api/health`);
      if (!r.ok) throw new Error(String(r.status));
      toast.success("Server terhubung.");
    } catch { toast.error("Server tidak merespons di alamat ini."); }
    finally { setTesting(false); }
  }
  function save() {
    if (invalid) return;
    setBackendUrl(normalized);
    toast.success("Tersimpan. Memuat ulang…");
    setTimeout(() => location.reload(), 600);
  }

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Pengaturan</h1>
      {isDesktop() ? <DesktopSettings /> : <Card className="flex flex-col gap-4 p-6">
        <div className="flex items-center gap-2"><Server className="size-4 text-primary" aria-hidden /><h2 className="font-semibold">Server pemrosesan</h2></div>
        <p className="text-sm text-muted">Kosongkan untuk memakai server di komputer ini. Isi alamat jika pemrosesan dilakukan di server GPU terpisah.</p>
        <Field label="Alamat server" hint="Contoh: https://rekamind.kantor.id" error={invalid ? "Alamat harus diawali http:// atau https://" : undefined}>
          {(id, d) => <Input id={id} aria-describedby={d} aria-invalid={invalid} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="(server lokal)" inputMode="url" />}
        </Field>
        <div className="flex gap-2">
          <Button onClick={() => void test()} loading={testing} disabled={invalid}>Uji koneksi</Button>
          <Button variant="primary" onClick={save} disabled={invalid || normalized === getBackendUrl()}>Simpan</Button>
        </div>
        <p className="text-xs text-muted">Catatan: login pengguna belum aktif. Jangan arahkan ke server yang terbuka ke internet.</p>
      </Card>}

      <Card className="flex flex-col gap-3 p-6">
        <h2 className="font-semibold">Status server</h2>
        <p className="flex items-center gap-2 text-sm">
          {health.isError ? <><XCircle className="size-4 text-danger" aria-hidden /> Tidak terhubung</> :
            <><CheckCircle2 className="size-4 text-success" aria-hidden /> Terhubung{health.data && ` · versi ${health.data.version}`}</>}
        </p>
        {caps.data && (
          caps.data.processing_ready ? (
            <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
              {Object.entries(caps.data.engines).map(([k, v]) => (<><dt key={k} className="text-muted">{({ transcriber: "Transkripsi", diarizer: "Pengenal pembicara", extractor: "Ringkasan & task" } as Record<string, string>)[k] ?? k}</dt><dd key={k + "v"}>{v}</dd></>))}
            </dl>
          ) : <p className="text-sm text-muted">Server ini belum dikonfigurasi untuk memproses rekaman.</p>
        )}
      </Card>
    </div>
  );
}

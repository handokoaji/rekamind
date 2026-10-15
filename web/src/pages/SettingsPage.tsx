import { CheckCircle2, Server, XCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { IntegrationsCard } from "../components/IntegrationsCard";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { isDesktop } from "../desktop/bridge";
import { DesktopSettings } from "../desktop/DesktopSettings";
import { Field, Input } from "../components/ui/Field";
import { useCapabilities, useHealth } from "../hooks/queries";
import { useTimeZoneChoice, zoneOptions } from "../hooks/timezone";
import { Select } from "../components/ui/Field";
import { getBackendUrl, normalizeBackendUrl, setBackendUrl } from "../lib/api";
import { t } from "../lib/i18n";

function TimeZoneCard({ serverZone, serverLabel }: { serverZone?: string; serverLabel?: string }) {
  const { choice, setChoice } = useTimeZoneChoice();
  return (
    <Card className="flex flex-col gap-3 p-6">
      <h2 className="font-semibold">{t("Zona waktu")}</h2>
      <Field label={t("Tampilkan jam rapat dalam")} hint={t("Server memakai {label} ({zone}); ini juga zona untuk tenggat \"besok\"/\"Jumat depan\" dan jam di berkas ekspor. Pilihan di sini hanya mengubah tampilan di perangkat ini.", { label: serverLabel ?? "WIB", zone: serverZone ?? "Asia/Jakarta" })}>
        {(id, d) => <Select id={id} aria-describedby={d} value={choice} onChange={(e) => setChoice(e.target.value)}>
          {zoneOptions().map((z) => <option key={z.value} value={z.value}>{z.label}</option>)}</Select>}
      </Field>
    </Card>
  );
}

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
      toast.success(t("Server terhubung."));
    } catch { toast.error(t("Server tidak merespons di alamat ini.")); }
    finally { setTesting(false); }
  }
  function save() {
    if (invalid) return;
    setBackendUrl(normalized);
    toast.success(t("Tersimpan. Memuat ulang…"));
    setTimeout(() => location.reload(), 600);
  }

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">{t("Pengaturan")}</h1>
      {isDesktop() ? <DesktopSettings /> : <Card className="flex flex-col gap-4 p-6">
        <div className="flex items-center gap-2"><Server className="size-4 text-primary" aria-hidden /><h2 className="font-semibold">{t("Server pemrosesan")}</h2></div>
        <p className="text-sm text-muted">{t("Kosongkan untuk memakai server di komputer ini. Isi alamat jika pemrosesan dilakukan di server GPU terpisah.")}</p>
        <Field label={t("Alamat server")} hint={t("Contoh: https://rekamind.kantor.id")} error={invalid ? t("Alamat harus diawali http:// atau https://") : undefined}>
          {(id, d) => <Input id={id} aria-describedby={d} aria-invalid={invalid} value={url} onChange={(e) => setUrl(e.target.value)} placeholder={t("(server lokal)")} inputMode="url" />}
        </Field>
        <div className="flex gap-2">
          <Button onClick={() => void test()} loading={testing} disabled={invalid}>{t("Uji koneksi")}</Button>
          <Button variant="primary" onClick={save} disabled={invalid || normalized === getBackendUrl()}>{t("Simpan")}</Button>
        </div>
      </Card>}

      <IntegrationsCard />

      <TimeZoneCard serverZone={caps.data?.timezone} serverLabel={caps.data?.timezone_label} />

      <Card className="flex flex-col gap-3 p-6">
        <h2 className="font-semibold">{t("Status server")}</h2>
        <p className="flex items-center gap-2 text-sm">
          {health.isError ? <><XCircle className="size-4 text-danger" aria-hidden /> {t("Tidak terhubung")}</> :
            <><CheckCircle2 className="size-4 text-success" aria-hidden /> {health.data ? t("Terhubung · versi {v}", { v: health.data.version }) : t("Terhubung")}</>}
        </p>
        {caps.data && (
          caps.data.processing_ready ? (
            <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
              {Object.entries(caps.data.engines).map(([k, v]) => (<><dt key={k} className="text-muted">{({ transcriber: t("Transkripsi"), diarizer: t("Pengenal pembicara"), extractor: t("Ringkasan & task") } as Record<string, string>)[k] ?? k}</dt><dd key={k + "v"}>{v}</dd></>))}
            </dl>
          ) : <p className="text-sm text-muted">{t("Server ini belum dikonfigurasi untuk memproses rekaman.")}</p>
        )}
      </Card>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { t } from "../lib/i18n";
import { desktop } from "./bridge";

const SIX_HOURS = 6 * 60 * 60 * 1000;

/** A newer release exists on GitHub: say so, with one button that downloads, checks and installs it.
 *  The shell refuses while a recording or upload is running, and the error is shown here. */
export function UpdateBanner() {
  const q = useQuery({ queryKey: ["update"], queryFn: desktop.checkUpdate, retry: false, staleTime: SIX_HOURS, refetchInterval: SIX_HOURS });
  const [hidden, setHidden] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const u = q.data;
  if (!u || hidden === u.version) return null;

  const install = async () => {
    setBusy(true);
    setError(null);
    try { await desktop.installUpdate(); } // on success the app quits and the installer takes over
    catch (e) { setError(e instanceof Error ? e.message : String(e)); setBusy(false); }
  };
  return (
    <Card className="flex flex-wrap items-center gap-4 border-primary/40 bg-primary-soft p-4">
      <Download className="size-5 shrink-0 text-primary" aria-hidden />
      <div className="min-w-60 flex-1 text-sm">
        <p className="font-semibold text-primary">{t("Versi {version} tersedia", { version: u.version })}</p>
        <p className="text-fg">
          {u.installer_url ? t("Pembaruan diunduh dan dipasang otomatis, lalu Rekamind dibuka lagi.") : t("Buka halaman rilis untuk mengunduh versi baru.")}
        </p>
        {error && <p role="alert" className="mt-1 text-danger">{error}</p>}
      </div>
      <Button variant="ghost" onClick={() => setHidden(u.version)} disabled={busy}>{t("Nanti")}</Button>
      <Button variant="primary" onClick={() => void install()} loading={busy}>
        {busy ? t("Mengunduh pembaruan…") : u.installer_url ? t("Perbarui sekarang") : t("Buka halaman rilis")}
      </Button>
    </Card>
  );
}

import { useState } from "react";
import { Button } from "../components/ui/Button";
import { ErrorState } from "../components/ui/Feedback";
import { t } from "../lib/i18n";
import { desktop } from "./bridge";
import { DesktopSettings } from "./DesktopSettings";

/** The server cannot be reached, so nothing behind the sign-in (including the Settings page) can open.
 *  Without this the error says "check the server address in Settings" with no way to get there. */
export function DesktopRecovery({ error, reload = () => window.location.reload() }: { error: unknown; reload?: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  // Local mode needs no server and no sign-in: recordings and history on this computer work again at once.
  const useLocal = async () => {
    setBusy(true);
    setFailed(null);
    try {
      const view = await desktop.settings();
      await desktop.saveSettings({ ...view.settings, mode: "local" });
      reload();
    } catch (e) {
      setFailed(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-4 px-4 py-8">
      <ErrorState error={error} onRetry={reload} />
      <div className="flex flex-wrap justify-center gap-2">
        <Button variant="primary" onClick={() => void useLocal()} loading={busy}>{t("Pakai mode lokal")}</Button>
        <Button variant="secondary" aria-expanded={open} onClick={() => setOpen((o) => !o)} disabled={busy}>
          {open ? t("Sembunyikan pengaturan") : t("Ubah pengaturan server")}
        </Button>
      </div>
      {failed && <p role="alert" className="text-center text-sm text-danger">{failed}</p>}
      {open && <DesktopSettings />}
    </main>
  );
}

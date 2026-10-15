import { Cpu } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { useBackendReady } from "./backend";
import { t } from "../lib/i18n";

/** First run on a machine: recording works, but nothing can be transcribed until the engines are
 *  installed. Say so where the user is looking, with the one action that fixes it. */
export function EngineSetupBanner({ ready }: { ready: boolean | undefined }) {
  const { mode } = useBackendReady();
  if (mode !== "local" || ready !== false) return null;
  return (
    <Card className="flex flex-wrap items-center gap-4 border-warning/40 bg-warning-soft p-4">
      <Cpu className="size-5 shrink-0 text-warning" aria-hidden />
      <div className="min-w-60 flex-1 text-sm">
        <p className="font-semibold text-warning">{t("Mesin transkripsi belum dipasang")}</p>
        <p className="text-fg">{t("Anda tetap bisa merekam sekarang. Pasang mesin sekali saja untuk membuat transkrip, ringkasan, dan task di komputer ini.")}</p>
      </div>
      <Link to="/pengaturan"><Button variant="primary">{t("Pasang mesin")}</Button></Link>
    </Card>
  );
}

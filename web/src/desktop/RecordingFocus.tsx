import { Info } from "lucide-react";
import { t } from "../lib/i18n";
import { RecordCard } from "./RecordCard";

/** While recording with the local backend, the list, tasks and settings cannot work (the backend is off on
 *  purpose), so they are not shown at all: one screen with the timer, the levels and the stop button. */
export function RecordingFocus() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <RecordCard />
      <p className="flex items-start gap-2 rounded-xl bg-primary-soft px-4 py-3 text-sm">
        <Info className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
        {t("Daftar rapat, task, dan pengaturan disembunyikan selama merekam agar perekaman tidak terganggu. Semuanya kembali setelah rekaman dihentikan.")}
      </p>
    </div>
  );
}

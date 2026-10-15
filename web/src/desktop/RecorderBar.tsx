import { Circle, Square } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "../components/ui/Button";
import { clock, StopDialog } from "./RecordCard";
import { useRecorder } from "./useRecorder";
import { t } from "../lib/i18n";

/** Visible on every page while recording: nobody should be able to forget that it is on. */
export function RecorderBar() {
  const { state, stop } = useRecorder();
  const [confirm, setConfirm] = useState(false);
  if (state?.phase !== "recording") return null;
  const trouble = state.sources.find((s) => s.state !== "recording");
  return (
    <div role="status" className="sticky top-0 z-30 border-b border-danger/30 bg-danger-soft">
      <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-2 text-sm">
        <Circle className="size-3 shrink-0 animate-pulse fill-danger text-danger motion-reduce:animate-none" aria-hidden />
        <span className="font-semibold text-danger">{t("Merekam")}</span>
        <span className="tabular-nums text-danger">{clock(state.elapsed_secs)}</span>
        <span className="hidden min-w-0 flex-1 truncate text-danger sm:block">{state.title}</span>
        {trouble && <span className="ml-auto text-warning">{trouble.label}: {trouble.message ?? t("bermasalah")}</span>}
        <Button size="sm" variant="danger" className={trouble ? "" : "ml-auto"} onClick={() => setConfirm(true)}><Square className="size-3.5 fill-current" aria-hidden /> {t("Hentikan")}</Button>
      </div>
      <StopDialog open={confirm} onOpenChange={setConfirm} onStop={() => void stop().catch((e: Error) => toast.error(e.message))} />
    </div>
  );
}

import { ChevronLeft, ChevronRight } from "lucide-react";
import { t } from "../lib/i18n";
import { Button } from "./ui/Button";

/** Previous / next with a page count. `total` is how many items there are in all, or null from a server that does not say
 *  (then "next" is offered while the page came back full). Renders nothing when everything fits on one page. */
export function Pagination({ page, size, total, count, onPage }: { page: number; size: number; total: number | null; count: number; onPage: (page: number) => void }) {
  const pages = total === null ? null : Math.max(1, Math.ceil(total / size));
  const hasPrev = page > 0;
  const hasNext = pages === null ? count === size : page + 1 < pages;
  if (!hasPrev && !hasNext) return null;
  return (
    <nav aria-label={t("Halaman rapat")} className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted">
      <span className="tabular-nums">
        {total === null ? t("Halaman {n}", { n: page + 1 }) : t("{from}–{to} dari {total} rapat", { from: page * size + 1, to: page * size + count, total })}
      </span>
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={!hasPrev} onClick={() => onPage(page - 1)}><ChevronLeft className="size-4" aria-hidden /> {t("Sebelumnya")}</Button>
        {pages !== null && <span className="tabular-nums" aria-live="polite">{t("Halaman {n} dari {m}", { n: page + 1, m: pages })}</span>}
        <Button size="sm" disabled={!hasNext} onClick={() => onPage(page + 1)}>{t("Berikutnya")} <ChevronRight className="size-4" aria-hidden /></Button>
      </div>
    </nav>
  );
}

import { AlertTriangle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import { t } from "../../lib/i18n";
import { Button } from "./Button";

export function Spinner({ label }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-16 text-sm text-muted">
      <Loader2 className="size-4 animate-spin" aria-hidden /> {label ?? t("Memuat…")}
    </div>
  );
}

export function EmptyState({ icon, title, children, action, as: Heading = "h2" }: { icon: ReactNode; title: string; children?: ReactNode; action?: ReactNode; as?: "h1" | "h2" }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
      <div className="grid size-14 place-items-center rounded-2xl bg-primary-soft text-primary" aria-hidden>{icon}</div>
      <Heading className="text-lg font-semibold">{title}</Heading>
      {children && <p className="max-w-md text-sm text-muted">{children}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-14 text-center">
      <div className="grid size-12 place-items-center rounded-2xl bg-danger-soft text-danger" aria-hidden><AlertTriangle className="size-6" /></div>
      <p className="max-w-md text-sm">{error instanceof Error ? error.message : t("Terjadi kesalahan.")}</p>
      {onRetry && <Button onClick={onRetry}>{t("Coba lagi")}</Button>}
    </div>
  );
}

export function ProgressBar({ value, label, className }: { value: number; label: string; className?: string }) {
  return (
    <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-border", className)}>
      <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${Math.max(4, value)}%` }} />
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-lg bg-border/70", className)} />;
}

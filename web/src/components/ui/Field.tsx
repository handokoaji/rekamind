import { useId, type ComponentProps, type ReactNode } from "react";
import { cn } from "../../lib/cn";

const control =
  "h-10 w-full rounded-lg border border-border bg-card px-3 text-sm text-fg placeholder:text-muted " +
  "transition-colors hover:border-muted/60 disabled:opacity-50";

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: (id: string, describedBy?: string) => ReactNode }) {
  const id = useId();
  const note = error ?? hint;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">{label}</label>
      {children(id, note ? `${id}-note` : undefined)}
      {note && <p id={`${id}-note`} className={cn("text-xs", error ? "text-danger" : "text-muted")}>{note}</p>}
    </div>
  );
}

export function Input({ className, ...p }: ComponentProps<"input">) {
  return <input {...p} className={cn(control, className)} />;
}

export function Select({ className, children, ...p }: ComponentProps<"select">) {
  return <select {...p} className={cn(control, "cursor-pointer pr-8", className)}>{children}</select>;
}

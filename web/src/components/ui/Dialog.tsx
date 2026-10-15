import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { t } from "../../lib/i18n";

/** Radix handles focus trap, Esc, scroll lock and aria wiring. */
export function Dialog({ open, onOpenChange, title, description, children }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: string; children: ReactNode;
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" />
        <D.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border border-border bg-card p-6 shadow-2xl">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <D.Title className="text-lg font-semibold">{title}</D.Title>
              <D.Description className={description ? "mt-1 text-sm text-muted" : "sr-only"}>{description ?? title}</D.Description>
            </div>
            <D.Close className="rounded-lg p-1.5 text-muted hover:bg-primary-soft hover:text-fg" aria-label={t("Tutup")}>
              <X className="size-4" />
            </D.Close>
          </div>
          {children}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

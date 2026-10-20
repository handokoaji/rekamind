import type { ReactNode } from "react";
import { desktop, isDesktop } from "../desktop/bridge";
import { cn } from "../lib/cn";

/** A link to another site. In a browser it is a normal link. Inside the desktop app a click would replace the app itself
 *  with that site, so the shell opens it in the system browser instead (and only for the few addresses it allows).
 *  `label` names a link that shows only an icon: it becomes the accessible name and the tooltip. */
export function ExternalLink({ href, children, className, label }: { href: string; children: ReactNode; className?: string; label?: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={label}
      title={label}
      onClick={(e) => {
        if (!isDesktop()) return;
        e.preventDefault();
        void desktop.openExternal(href).catch(() => undefined);
      }}
      className={cn("underline decoration-muted/50 underline-offset-4 transition-colors hover:text-fg hover:decoration-current", className)}
    >
      {children}
    </a>
  );
}

/** The quiet look of an icon-only link: muted, no underline, a little darker on hover. */
export const iconLink = "inline-flex items-center rounded-md text-muted no-underline hover:text-fg";

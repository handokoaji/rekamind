import { LANGS, setLang, useLang } from "../lib/i18n";
import { cn } from "../lib/cn";

/** Two buttons, not a native <select>: a select's popup is painted by the OS, outside our theme, and its
 *  hover state turned every label white-on-white. Always labelled in both languages, so someone who
 *  cannot read the current one can still find it. */
export function LanguageSwitcher({ className = "" }: { className?: string }) {
  const lang = useLang();
  return (
    <div role="group" aria-label="Bahasa / Language" className={cn("inline-flex h-8 shrink-0 items-center rounded-lg border border-border bg-card p-0.5 text-xs font-semibold", className)}>
      {LANGS.map((l) => {
        const active = l.code === lang;
        return (
          <button key={l.code} type="button" lang={l.code} aria-pressed={active} aria-label={l.label} title={l.label}
            onClick={() => setLang(l.code)}
            className={cn("h-full rounded-md px-2.5 transition-colors",
              active ? "bg-primary text-primary-fg" : "text-muted hover:bg-primary-soft hover:text-fg")}>
            {l.code.toUpperCase()}
          </button>
        );
      })}
    </div>
  );
}

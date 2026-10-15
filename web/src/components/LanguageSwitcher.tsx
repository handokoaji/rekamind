import { LANGS, setLang, useLang, type Lang } from "../lib/i18n";

/** Always labelled in both languages, so someone who cannot read the current one can still find it. */
export function LanguageSwitcher({ className = "" }: { className?: string }) {
  const lang = useLang();
  return (
    <select
      aria-label="Bahasa / Language"
      value={lang}
      onChange={(e) => setLang(e.target.value as Lang)}
      className={`h-8 rounded-lg border border-border bg-surface px-2 text-sm text-fg ${className}`}
    >
      {LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
    </select>
  );
}

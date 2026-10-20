import { useTheme, type ThemeChoice } from "../hooks/theme";
import { cn } from "../lib/cn";
import { t } from "../lib/i18n";
import { Card } from "./ui/Card";

/** Light, dark, or whatever the system says (the default). Buttons like the language switcher, not a native select:
 *  a select's popup is painted by the operating system, outside our theme. */
export function ThemeCard() {
  const { choice, setChoice } = useTheme();
  const options: { value: ThemeChoice; label: string }[] = [
    { value: "system", label: t("Ikuti sistem") },
    { value: "light", label: t("Terang") },
    { value: "dark", label: t("Gelap") },
  ];
  return (
    <Card className="flex flex-col gap-3 p-6">
      <h2 className="font-semibold">{t("Tampilan")}</h2>
      <p className="text-sm text-muted">{t("Warna aplikasi. Bawaannya mengikuti pengaturan terang atau gelap di sistem Anda.")}</p>
      <div role="group" aria-label={t("Tema")} className="inline-flex h-9 w-fit items-center rounded-lg border border-border bg-bg p-0.5 text-sm font-medium">
        {options.map((o) => (
          <button key={o.value} type="button" aria-pressed={choice === o.value} onClick={() => setChoice(o.value)}
            className={cn("h-full rounded-md px-3.5 transition-colors", choice === o.value ? "bg-primary text-primary-fg" : "text-muted hover:text-fg")}>
            {o.label}
          </button>
        ))}
      </div>
    </Card>
  );
}

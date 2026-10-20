import { ABOUT, APP_VERSION } from "../lib/about";
import { t } from "../lib/i18n";
import { ExternalLink } from "./ExternalLink";
import { Logo } from "./Logo";
import { Card } from "./ui/Card";

/** Quiet by design: text and plain links, no buttons or colour. It sits at the end of Settings, where people look for
 *  "About", and never in the way of recording or reading a meeting. */
export function AboutCard() {
  return (
    <Card id="tentang" className="flex flex-col gap-4 p-6">
      <div className="flex items-center gap-3">
        <Logo className="size-9" />
        <div>
          <h2 className="font-semibold leading-tight">Rekamind</h2>
          <p className="text-xs text-muted">{t("Versi {v}", { v: APP_VERSION })} · AGPL-3.0-or-later</p>
        </div>
      </div>
      <p className="text-sm">
        {t("Dibuat oleh")} <ExternalLink href={ABOUT.github}>{ABOUT.name}</ExternalLink>
      </p>
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
        <ExternalLink href={ABOUT.repo}>{t("Kode sumber")}</ExternalLink>
        <ExternalLink href={`${ABOUT.repo}/issues`}>{t("Laporkan masalah")}</ExternalLink>
        <ExternalLink href={ABOUT.instagram}>Instagram</ExternalLink>
      </p>
      <p className="text-sm text-muted">
        {t("Rekamind gratis dan terbuka. Bila bermanfaat, Anda dapat mendukung pengembangannya lewat")}{" "}
        <ExternalLink href={ABOUT.sponsors}>GitHub Sponsors</ExternalLink> {t("atau")} <ExternalLink href={ABOUT.saweria}>Saweria</ExternalLink>.
      </p>
    </Card>
  );
}

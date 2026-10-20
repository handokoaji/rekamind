import { Coffee, Heart } from "lucide-react";
import { ABOUT, APP_VERSION } from "../lib/about";
import { t } from "../lib/i18n";
import { ExternalLink, iconLink } from "./ExternalLink";
import { InstagramIcon } from "./icons";
import { Logo } from "./Logo";
import { Card } from "./ui/Card";

const dot = <span aria-hidden className="mx-2 text-border">·</span>;

/** Quiet by design: text and plain links, icons only for the social and support links, no buttons, no colour. It sits at
 *  the end of Settings, where people look for "About", and never in the way of recording or reading a meeting. */
export function AboutCard() {
  return (
    <Card id="tentang" className="p-6">
      <div className="flex items-center gap-3">
        <Logo className="size-9" />
        <div className="min-w-0">
          <h2 className="font-semibold leading-tight">Rekamind</h2>
          <p className="text-xs text-muted">{t("Versi {v}", { v: APP_VERSION })}{dot}AGPL-3.0-or-later</p>
        </div>
      </div>

      <dl className="mt-5 grid grid-cols-[max-content_1fr] items-center gap-x-6 gap-y-2 text-sm">
        <dt className="text-muted">{t("Dibuat oleh")}</dt>
        <dd className="flex items-center gap-3">
          <ExternalLink href={ABOUT.github}>{ABOUT.name}</ExternalLink>
          <ExternalLink href={ABOUT.instagram} label="Instagram" className={iconLink}><InstagramIcon /></ExternalLink>
        </dd>
        <dt className="text-muted">{t("Proyek")}</dt>
        <dd>
          <ExternalLink href={ABOUT.repo}>{t("Kode sumber")}</ExternalLink>
          {dot}
          <ExternalLink href={`${ABOUT.repo}/issues`}>{t("Laporkan masalah")}</ExternalLink>
        </dd>
      </dl>

      <div className="mt-5 flex items-center justify-between gap-4 border-t border-border pt-4">
        <p className="text-xs leading-relaxed text-muted">{t("Rekamind gratis dan terbuka. Bila bermanfaat, Anda dapat mendukung pengembangannya.")}</p>
        <div className="flex shrink-0 items-center gap-3">
          <ExternalLink href={ABOUT.sponsors} label="GitHub Sponsors" className={iconLink}><Heart className="size-4" aria-hidden /></ExternalLink>
          <ExternalLink href={ABOUT.saweria} label="Saweria" className={iconLink}><Coffee className="size-4" aria-hidden /></ExternalLink>
        </div>
      </div>
    </Card>
  );
}

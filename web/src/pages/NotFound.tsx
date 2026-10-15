import { Compass } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/Feedback";
import { t } from "../lib/i18n";

export function NotFound() {
  return <Card><EmptyState as="h1" icon={<Compass className="size-6" />} title={t("Halaman tidak ditemukan")} action={<Link to="/"><Button variant="primary">{t("Ke daftar rapat")}</Button></Link>}>{t("Alamat ini tidak ada di Rekamind.")}</EmptyState></Card>;
}

import { LogOut } from "lucide-react";
import { useAuth } from "../hooks/auth";
import { t } from "../lib/i18n";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";

export function UserMenu() {
  const { me, logout, isSuperadmin } = useAuth();
  if (me.auth_mode !== "google") return null; // single-user modes have no one to sign out
  const initials = (me.name ?? me.email).slice(0, 2).toUpperCase();
  return (
    <div className="flex items-center gap-2">
      <div className="hidden text-right leading-tight sm:block">
        <p className="max-w-40 truncate text-sm font-medium">{me.name ?? me.email}</p>
        <p className="max-w-40 truncate text-xs text-muted">{me.email}</p>
      </div>
      {isSuperadmin && <Badge tone="primary">{t("Super admin")}</Badge>}
      {me.picture
        ? <img src={me.picture} alt="" referrerPolicy="no-referrer" className="size-8 rounded-full" />
        : <span className="grid size-8 place-items-center rounded-full bg-primary-soft text-xs font-bold text-primary" aria-hidden>{initials}</span>}
      <Button size="sm" variant="ghost" onClick={() => void logout()} aria-label={t("Keluar")}><LogOut className="size-4" aria-hidden /></Button>
    </div>
  );
}

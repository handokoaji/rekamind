import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, ShieldCheck, UserCheck, UserX } from "lucide-react";
import { useState } from "react";
import { Navigate } from "react-router-dom";
import { toast } from "sonner";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Dialog } from "../components/ui/Dialog";
import { ErrorState, Skeleton } from "../components/ui/Feedback";
import { Field, Input, Select } from "../components/ui/Field";
import { useAuth } from "../hooks/auth";
import { api } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { t } from "../lib/i18n";
import type { AdminUser, Role } from "../lib/types";

function UserRow({ u, self }: { u: AdminUser; self: boolean }) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState<null | { title: string; body: string; patch: { role?: Role; disabled?: boolean } }>(null);
  const patch = useMutation({
    mutationFn: (p: { role?: Role; disabled?: boolean }) => api.patchUser(u.id, p),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["admin-users"] }); setConfirm(null); toast.success(t("Tersimpan.")); },
    onError: (e: Error) => { setConfirm(null); toast.error(e.message); },
  });
  const isAdmin = u.role === "superadmin";
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-border bg-card px-4 py-3">
      <div className="min-w-0 flex-1 basis-60">
        <p className="truncate font-medium">{u.name ?? u.email}{self && <span className="ml-2 text-xs text-muted">{t("(Anda)")}</span>}</p>
        <p className="truncate text-sm text-muted">{u.name ? u.email : t("Belum pernah masuk")}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {isAdmin ? <Badge tone="primary" icon={<ShieldCheck className="size-3" />}>{t("Super admin")}</Badge> : <Badge>{t("Pengguna")}</Badge>}
        {u.invited && <Badge tone="info" icon={<Mail className="size-3" />}>{t("Diundang")}</Badge>}
        {u.disabled && <Badge tone="danger" icon={<UserX className="size-3" />}>{t("Nonaktif")}</Badge>}
      </div>
      <p className="w-28 text-right text-xs text-muted tabular-nums">{t("{n} rapat", { n: u.meetings })}{u.last_login_at && <><br />{t("masuk {date}", { date: formatDateTime(u.last_login_at) })}</>}</p>
      <div className="flex gap-1">
        <Button size="sm" onClick={() => setConfirm({
          title: isAdmin ? t("Cabut hak super admin {email}?", { email: u.email }) : t("Jadikan {email} super admin?", { email: u.email }),
          body: isAdmin ? t("Orang ini tidak akan bisa lagi mengelola pengguna atau melihat rapat orang lain.") : t("Super admin bisa melakukan apa pun: mengelola pengguna dan melihat serta mengubah rapat semua orang."),
          patch: { role: isAdmin ? "user" : "superadmin" } })}>
          {isAdmin ? t("Cabut super admin") : t("Jadikan super admin")}
        </Button>
        <Button size="sm" variant={u.disabled ? "secondary" : "danger"} onClick={() => setConfirm({
          title: u.disabled ? t("Aktifkan kembali {email}?", { email: u.email }) : t("Nonaktifkan {email}?", { email: u.email }),
          body: u.disabled ? t("Orang ini bisa masuk lagi. Sesi lamanya tetap tidak berlaku; ia perlu masuk ulang.") : t("Semua sesinya langsung berakhir dan ia tidak bisa masuk. Rapatnya tetap tersimpan."),
          patch: { disabled: !u.disabled } })}>
          {u.disabled ? <><UserCheck className="size-3.5" aria-hidden /> {t("Aktifkan")}</> : <><UserX className="size-3.5" aria-hidden /> {t("Nonaktifkan")}</>}
        </Button>
      </div>
      {confirm && (
        <Dialog open onOpenChange={(o) => !o && setConfirm(null)} title={confirm.title} description={confirm.body}>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" autoFocus onClick={() => setConfirm(null)}>{t("Batal")}</Button>
            <Button variant="primary" loading={patch.isPending} onClick={() => patch.mutate(confirm.patch)}>{t("Ya, lanjutkan")}</Button>
          </div>
        </Dialog>)}
    </li>
  );
}

export function AdminPage() {
  const { me, canAdmin } = useAuth();
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["admin-users"], queryFn: api.adminUsers, enabled: canAdmin });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("user");
  const invite = useMutation({
    mutationFn: () => api.inviteUser(email.trim(), role),
    onSuccess: () => { setEmail(""); setRole("user"); void qc.invalidateQueries({ queryKey: ["admin-users"] }); toast.success(t("Undangan dibuat. Orang ini bisa langsung masuk dengan akun Google tersebut.")); },
    onError: (e: Error) => toast.error(e.message),
  });
  if (!canAdmin) return <Navigate to="/" replace />;

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{t("Pengguna")}</h1>
        <p className="mt-1 text-sm text-muted">{t("Siapa yang boleh masuk ke server ini. Pengguna biasa hanya melihat rapat miliknya sendiri; super admin bisa melakukan apa pun.")}</p>
      </div>
      <Card className="p-6">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (email.trim()) invite.mutate(); }}>
          <div className="min-w-60 flex-1">
            <Field label={t("Undang dengan email Google")}>{(id) => <Input id={id} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder={t("nama@kantor.id")} />}</Field>
          </div>
          <div className="w-44">
            <Field label={t("Peran")}>{(id) => <Select id={id} value={role} onChange={(e) => setRole(e.target.value as Role)}><option value="user">{t("Pengguna")}</option><option value="superadmin">{t("Super admin")}</option></Select>}</Field>
          </div>
          <Button type="submit" variant="primary" loading={invite.isPending}>{t("Undang")}</Button>
        </form>
      </Card>
      {users.isLoading ? <Skeleton className="h-48" /> : users.error ? <Card><ErrorState error={users.error} onRetry={() => void users.refetch()} /></Card> : (
        <ul className="flex flex-col gap-2" aria-label={t("Daftar pengguna")}>{users.data?.map((u) => <UserRow key={u.id} u={u} self={u.id === me.id} />)}</ul>
      )}
    </div>
  );
}

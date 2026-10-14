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
import type { AdminUser, Role } from "../lib/types";

function UserRow({ u, self }: { u: AdminUser; self: boolean }) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState<null | { title: string; body: string; patch: { role?: Role; disabled?: boolean } }>(null);
  const patch = useMutation({
    mutationFn: (p: { role?: Role; disabled?: boolean }) => api.patchUser(u.id, p),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["admin-users"] }); setConfirm(null); toast.success("Tersimpan."); },
    onError: (e: Error) => { setConfirm(null); toast.error(e.message); },
  });
  const isAdmin = u.role === "superadmin";
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-border bg-card px-4 py-3">
      <div className="min-w-0 flex-1 basis-60">
        <p className="truncate font-medium">{u.name ?? u.email}{self && <span className="ml-2 text-xs text-muted">(Anda)</span>}</p>
        <p className="truncate text-sm text-muted">{u.name ? u.email : "Belum pernah masuk"}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {isAdmin ? <Badge tone="primary" icon={<ShieldCheck className="size-3" />}>Super admin</Badge> : <Badge>Pengguna</Badge>}
        {u.invited && <Badge tone="info" icon={<Mail className="size-3" />}>Diundang</Badge>}
        {u.disabled && <Badge tone="danger" icon={<UserX className="size-3" />}>Nonaktif</Badge>}
      </div>
      <p className="w-28 text-right text-xs text-muted tabular-nums">{u.meetings} rapat{u.last_login_at && <><br />masuk {formatDateTime(u.last_login_at)}</>}</p>
      <div className="flex gap-1">
        <Button size="sm" onClick={() => setConfirm({
          title: isAdmin ? `Cabut hak super admin ${u.email}?` : `Jadikan ${u.email} super admin?`,
          body: isAdmin ? "Orang ini tidak akan bisa lagi mengelola pengguna atau melihat rapat orang lain." : "Super admin bisa melakukan apa pun: mengelola pengguna dan melihat serta mengubah rapat semua orang.",
          patch: { role: isAdmin ? "user" : "superadmin" } })}>
          {isAdmin ? "Cabut super admin" : "Jadikan super admin"}
        </Button>
        <Button size="sm" variant={u.disabled ? "secondary" : "danger"} onClick={() => setConfirm({
          title: u.disabled ? `Aktifkan kembali ${u.email}?` : `Nonaktifkan ${u.email}?`,
          body: u.disabled ? "Orang ini bisa masuk lagi. Sesi lamanya tetap tidak berlaku; ia perlu masuk ulang." : "Semua sesinya langsung berakhir dan ia tidak bisa masuk. Rapatnya tetap tersimpan.",
          patch: { disabled: !u.disabled } })}>
          {u.disabled ? <><UserCheck className="size-3.5" aria-hidden /> Aktifkan</> : <><UserX className="size-3.5" aria-hidden /> Nonaktifkan</>}
        </Button>
      </div>
      {confirm && (
        <Dialog open onOpenChange={(o) => !o && setConfirm(null)} title={confirm.title} description={confirm.body}>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" autoFocus onClick={() => setConfirm(null)}>Batal</Button>
            <Button variant="primary" loading={patch.isPending} onClick={() => patch.mutate(confirm.patch)}>Ya, lanjutkan</Button>
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
    onSuccess: () => { setEmail(""); setRole("user"); void qc.invalidateQueries({ queryKey: ["admin-users"] }); toast.success("Undangan dibuat. Orang ini bisa langsung masuk dengan akun Google tersebut."); },
    onError: (e: Error) => toast.error(e.message),
  });
  if (!canAdmin) return <Navigate to="/" replace />;

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Pengguna</h1>
        <p className="mt-1 text-sm text-muted">Siapa yang boleh masuk ke server ini. Pengguna biasa hanya melihat rapat miliknya sendiri; super admin bisa melakukan apa pun.</p>
      </div>
      <Card className="p-6">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (email.trim()) invite.mutate(); }}>
          <div className="min-w-60 flex-1">
            <Field label="Undang dengan email Google">{(id) => <Input id={id} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="nama@kantor.id" />}</Field>
          </div>
          <div className="w-44">
            <Field label="Peran">{(id) => <Select id={id} value={role} onChange={(e) => setRole(e.target.value as Role)}><option value="user">Pengguna</option><option value="superadmin">Super admin</option></Select>}</Field>
          </div>
          <Button type="submit" variant="primary" loading={invite.isPending}>Undang</Button>
        </form>
      </Card>
      {users.isLoading ? <Skeleton className="h-48" /> : users.error ? <Card><ErrorState error={users.error} onRetry={() => void users.refetch()} /></Card> : (
        <ul className="flex flex-col gap-2" aria-label="Daftar pengguna">{users.data?.map((u) => <UserRow key={u.id} u={u} self={u.id === me.id} />)}</ul>
      )}
    </div>
  );
}

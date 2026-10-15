import { useQueryClient } from "@tanstack/react-query";
import { GitBranch, Plug, Plus, Trash2, Webhook } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useIntegrationStatus, useIntegrations } from "../hooks/queries";
import { api } from "../lib/api";
import type { Integration, IntegrationKind } from "../lib/types";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card } from "./ui/Card";
import { Field, Input, Select } from "./ui/Field";

const KINDS: { value: IntegrationKind; label: string }[] = [
  { value: "github", label: "GitHub Issues" }, { value: "gitlab", label: "GitLab Issues" }, { value: "webhook", label: "Webhook (sistem lain)" },
];

/** "Budi = budi-gh" per line -> { Budi: "budi-gh" } */
function parseMap(text: string, numeric: boolean): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  for (const line of text.split("\n")) {
    const [name, ...rest] = line.split("=");
    const v = rest.join("=").trim();
    if (name?.trim() && v) out[name.trim()] = numeric && /^\d+$/.test(v) ? Number(v) : v;
  }
  return out;
}

function AddForm({ onDone }: { onDone: () => void }) {
  const [kind, setKind] = useState<IntegrationKind>("github");
  const [name, setName] = useState("");
  const [f, setF] = useState({ repo: "", project: "", base: "", url: "", labels: "rekamind", map: "", secret: "" });
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f, v: string) => setF((p) => ({ ...p, [k]: v }));

  async function save() {
    setBusy(true);
    const labels = f.labels.split(",").map((x) => x.trim()).filter(Boolean);
    const config: Record<string, unknown> = kind === "webhook" ? { url: f.url.trim() }
      : { ...(kind === "github" ? { repo: f.repo.trim() } : { project: f.project.trim() }), ...(f.base.trim() ? { base_url: f.base.trim() } : {}), labels, assignees: parseMap(f.map, kind === "gitlab") };
    try {
      await api.createIntegration({ kind, name: name.trim() || KINDS.find((k) => k.value === kind)!.label, config, secret: f.secret || undefined });
      toast.success("Integrasi disimpan.");
      onDone();
    } catch (e) { toast.error(e instanceof Error ? e.message : "Gagal menyimpan"); } finally { setBusy(false); }
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Jenis">{(id) => <Select id={id} value={kind} onChange={(e) => setKind(e.target.value as IntegrationKind)}>{KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}</Select>}</Field>
        <Field label="Nama tampilan" hint="Mis. “Repo proyek A”.">{(id, d) => <Input id={id} aria-describedby={d} value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />}</Field>
      </div>
      {kind === "webhook" ? (
        <Field label="URL penerima" hint="Rekamind mengirim JSON bertanda tangan HMAC-SHA256 (header X-Rekamind-Signature).">{(id, d) => <Input id={id} aria-describedby={d} inputMode="url" placeholder="https://tasks.kantor.id/hook" value={f.url} onChange={(e) => set("url", e.target.value)} />}</Field>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            {kind === "github"
              ? <Field label="Repositori" hint="Bentuk pemilik/nama.">{(id, d) => <Input id={id} aria-describedby={d} placeholder="kantor/proyek" value={f.repo} onChange={(e) => set("repo", e.target.value)} />}</Field>
              : <Field label="Proyek" hint="Path (grup/proyek) atau ID angka.">{(id, d) => <Input id={id} aria-describedby={d} placeholder="kantor/proyek" value={f.project} onChange={(e) => set("project", e.target.value)} />}</Field>}
            <Field label="Alamat server (opsional)" hint={kind === "github" ? "Kosongkan untuk github.com; isi untuk GitHub Enterprise." : "Kosongkan untuk gitlab.com; isi untuk GitLab sendiri."}>{(id, d) => <Input id={id} aria-describedby={d} inputMode="url" placeholder={kind === "github" ? "https://api.github.com" : "https://gitlab.kantor.id"} value={f.base} onChange={(e) => set("base", e.target.value)} />}</Field>
          </div>
          <Field label="Label" hint="Pisahkan dengan koma.">{(id) => <Input id={id} value={f.labels} onChange={(e) => set("labels", e.target.value)} />}</Field>
          <Field label="Pemetaan PIC (opsional)" hint={`Satu per baris: nama seperti yang diucapkan = ${kind === "github" ? "username GitHub" : "ID pengguna GitLab"}. Nama yang tidak ada di sini dikirim tanpa assignee (tetap tertulis di deskripsi).`}>
            {(id, d) => <textarea id={id} aria-describedby={d} rows={3} className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm" placeholder={kind === "github" ? "Budi = budi-gh" : "Budi = 12345"} value={f.map} onChange={(e) => set("map", e.target.value)} />}</Field>
        </>)}
      <Field label={kind === "webhook" ? "Rahasia tanda tangan (opsional)" : "Token akses"} hint="Disimpan terenkripsi di server dan tidak pernah ditampilkan lagi.">
        {(id, d) => <Input id={id} aria-describedby={d} type="password" autoComplete="off" value={f.secret} onChange={(e) => set("secret", e.target.value)} />}</Field>
      <div className="flex gap-2"><Button variant="primary" loading={busy} onClick={() => void save()}>Simpan</Button><Button variant="ghost" onClick={onDone}>Batal</Button></div>
    </div>
  );
}

function Row({ i, onChanged }: { i: Integration; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const run = async (fn: () => Promise<unknown>) => { setBusy(true); try { await fn(); onChanged(); } catch (e) { toast.error(e instanceof Error ? e.message : "Gagal"); } finally { setBusy(false); } };
  const target = i.kind === "webhook" ? String(i.config.url ?? "") : String(i.kind === "github" ? i.config.repo : i.config.project ?? "");
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        {i.kind === "webhook" ? <Webhook className="size-4 text-primary" aria-hidden /> : <GitBranch className="size-4 text-primary" aria-hidden />}
        <span className="font-medium">{i.name}</span>
        <Badge tone="neutral">{KINDS.find((k) => k.value === i.kind)?.label}</Badge>
        {!i.enabled && <Badge tone="warning">Nonaktif</Badge>}
        <span className="min-w-0 flex-1 truncate text-sm text-muted">{target}</span>
        <Button size="sm" variant="secondary" loading={busy} onClick={() => void run(async () => setResult(await api.testIntegration(i.id)))}>Uji integrasi</Button>
        <Button size="sm" variant="ghost" onClick={() => void run(() => api.patchIntegration(i.id, { enabled: !i.enabled }))}>{i.enabled ? "Nonaktifkan" : "Aktifkan"}</Button>
        {confirm
          ? <><Button size="sm" variant="danger" onClick={() => void run(() => api.deleteIntegration(i.id))}>Ya, hapus</Button><Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>Batal</Button></>
          : <Button size="sm" variant="ghost" aria-label={`Hapus ${i.name}`} onClick={() => setConfirm(true)}><Trash2 className="size-4" aria-hidden /></Button>}
      </div>
      {result && <p role={result.ok ? "status" : "alert"} className={result.ok ? "text-sm text-success" : "text-sm text-danger"}>{result.message}</p>}
    </li>
  );
}

export function IntegrationsCard() {
  const status = useIntegrationStatus();
  const list = useIntegrations();
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["integrations"] }); setAdding(false); };
  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex items-center gap-2"><Plug className="size-4 text-primary" aria-hidden /><h2 className="font-semibold">Integrasi task</h2></div>
      <p className="text-sm text-muted">Kirim task yang sudah Anda konfirmasi ke GitHub, GitLab, atau sistem lain. Tidak pernah otomatis: selalu lewat tombol Kirim di tab Task.</p>
      {status.data && !status.data.available
        ? <p role="alert" className="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">{status.data.reason}</p>
        : (
          <>
            {list.data?.length ? <ul className="flex flex-col gap-2">{list.data.map((i) => <Row key={i.id} i={i} onChanged={refresh} />)}</ul> : !adding && <p className="text-sm text-muted">Belum ada integrasi.</p>}
            {adding ? <AddForm onDone={refresh} /> : <Button className="self-start" onClick={() => setAdding(true)}><Plus className="size-4" aria-hidden /> Tambah integrasi</Button>}
          </>)}
    </Card>
  );
}

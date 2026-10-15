import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Send, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { useIntegrationStatus, useIntegrations, useLinks } from "../hooks/queries";
import { api } from "../lib/api";
import { t } from "../lib/i18n";
import type { PushResult, Task } from "../lib/types";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Select } from "./ui/Field";

/** Sending is always a deliberate click, and only ever for tasks a person confirmed. */
export function PushPanel({ meetingId, confirmed }: { meetingId: string; confirmed: Task[] }) {
  const status = useIntegrationStatus();
  const list = useIntegrations();
  const links = useLinks(meetingId);
  const qc = useQueryClient();
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<PushResult[] | null>(null);
  const usable = (list.data ?? []).filter((i) => i.enabled);
  useEffect(() => { if (!target && usable[0]) setTarget(usable[0].id); }, [target, usable]);

  if (!status.data?.available && !usable.length) return null; // nothing configured and nothing possible: stay out of the way
  if (!usable.length) {
    return <p className="text-sm text-muted">{t("Mau mengirim task ke GitHub, GitLab, atau sistem lain?")} <Link className="font-medium text-primary underline" to="/pengaturan">{t("Atur integrasi")}</Link>.</p>;
  }
  const mine = (links.data ?? []).filter((l) => l.integration_id === target);
  const synced = new Set(mine.filter((l) => l.state === "synced").map((l) => l.task_id));
  const pending = confirmed.filter((c) => !synced.has(c.id)).length;

  async function send() {
    setBusy(true); setResults(null);
    try {
      const r = await api.push(meetingId, target);
      setResults(r.results);
      const failed = r.results.filter((x) => x.status === "failed").length;
      const done = r.results.filter((x) => x.status === "created" || x.status === "updated").length;
      (failed ? toast.warning : toast.success)(failed ? t("{done} task terkirim ke {target}, {failed} gagal.", { done, target: r.integration, failed }) : t("{done} task terkirim ke {target}.", { done, target: r.integration }));
      await qc.invalidateQueries({ queryKey: ["links", meetingId] });
    } catch (e) { toast.error(e instanceof Error ? e.message : t("Gagal mengirim")); } finally { setBusy(false); }
  }

  return (
    <section aria-labelledby="push-h" className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h4 id="push-h" className="text-sm font-semibold">{t("Kirim task terkonfirmasi ke")}</h4>
        <Select aria-label={t("Tujuan")} className="h-9 w-auto min-w-48" value={target} onChange={(e) => { setTarget(e.target.value); setResults(null); }}>
          {usable.map((i) => <option key={i.id} value={i.id}>{i.name} ({i.kind})</option>)}</Select>
        <Button variant="primary" size="sm" loading={busy} disabled={!target || !confirmed.length} onClick={() => void send()}>
          <Send className="size-3.5" aria-hidden /> {pending === confirmed.length ? t("Kirim {n} task", { n: confirmed.length }) : t("Kirim ulang ({n} baru/berubah)", { n: pending })}</Button>
      </div>
      <p className="text-xs text-muted">{t("Task yang sudah terkirim diperbarui di tempat yang sama (tidak digandakan); yang tidak berubah dilewati.")}</p>
      {mine.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label={t("Task yang sudah terkirim")}>
          {mine.map((l) => {
            const task = confirmed.find((x) => x.id === l.task_id);
            const name = task?.title.slice(0, 28) ?? t("Task");
            return <li key={l.task_id}>{l.state === "synced"
              ? <Badge tone="success">{l.url ? <a className="inline-flex items-center gap-1 underline" href={l.url} target="_blank" rel="noreferrer noopener">{name} · #{l.external_id ?? "ok"} <ExternalLink className="size-3" aria-hidden /></a> : t("{name} terkirim", { name })}</Badge>
              : <Badge tone="danger" icon={<TriangleAlert className="size-3" aria-hidden />}>{t("{name}: gagal", { name })}</Badge>}</li>;
          })}
        </ul>)}
      {results?.some((r) => r.status === "failed") && (
        <ul role="alert" className="flex flex-col gap-1 text-sm text-danger">
          {results.filter((r) => r.status === "failed").map((r) => <li key={r.task_id}><strong>{r.title}:</strong> {r.error}</li>)}
        </ul>)}
    </section>
  );
}

import { formatClock, formatDay, formatMinutes } from "./format";
import { priorityLabel } from "./strings";
import { t } from "./i18n";
import type { MeetingDetail, Participant, Task } from "./types";

export function assigneeName(t: Task, participants: Participant[]): string | null {
  const p = participants.find((x) => x.id === t.assignee_participant_id);
  return p ? (p.name ?? p.label) : t.assignee_name;
}

/** Stable, versioned shape: this is the contract the task-manager integration will read. */
export function tasksToJson(m: MeetingDetail, tasks: Task[]): string {
  return JSON.stringify(
    {
      schema: "rekamind.tasks/v1",
      meeting: { id: m.id, title: m.title, started_at: m.started_at },
      tasks: tasks.map((t) => ({
        id: t.id,
        title: t.title,
        description: t.description,
        assignee: assigneeName(t, m.participants),
        deadline: t.deadline,
        deadline_is_approximate: t.deadline_approximate,
        estimate_minutes: t.estimate_minutes,
        priority: t.priority,
        evidence: { start_ms: t.evidence_start_ms, quote: t.evidence_quote },
      })),
    },
    null, 2,
  );
}

export function tasksToMarkdown(m: MeetingDetail, tasks: Task[]): string {
  const lines = [t("# Task: {title}", { title: m.title }), ""];
  for (const k of tasks) {
    const who = assigneeName(k, m.participants);
    const meta = [
      who && t("PIC: {name}", { name: who }),
      k.deadline && (k.deadline_approximate ? t("Tenggat: {date} (perkiraan)", { date: formatDay(k.deadline) }) : t("Tenggat: {date}", { date: formatDay(k.deadline) })),
      k.estimate_minutes && t("Estimasi: {time}", { time: formatMinutes(k.estimate_minutes) }),
      t("Prioritas: {level}", { level: priorityLabel[k.priority] }),
    ].filter(Boolean);
    lines.push(`- [ ] **${k.title}** — ${meta.join(" · ")}`);
    if (k.description) lines.push(`  ${k.description}`);
    if (k.evidence_quote) lines.push(`  > ${k.evidence_quote}${k.evidence_start_ms != null ? ` (${formatClock(k.evidence_start_ms)})` : ""}`);
  }
  return lines.join("\n") + "\n";
}

export function download(filename: string, content: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

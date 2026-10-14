import { formatClock, formatDay, formatMinutes } from "./format";
import { priorityLabel } from "./strings";
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
  const lines = [`# Task: ${m.title}`, ""];
  for (const t of tasks) {
    const who = assigneeName(t, m.participants);
    const meta = [
      who && `PIC: ${who}`,
      t.deadline && `Tenggat: ${formatDay(t.deadline)}${t.deadline_approximate ? " (perkiraan)" : ""}`,
      t.estimate_minutes && `Estimasi: ${formatMinutes(t.estimate_minutes)}`,
      `Prioritas: ${priorityLabel[t.priority]}`,
    ].filter(Boolean);
    lines.push(`- [ ] **${t.title}** — ${meta.join(" · ")}`);
    if (t.description) lines.push(`  ${t.description}`);
    if (t.evidence_quote) lines.push(`  > ${t.evidence_quote}${t.evidence_start_ms != null ? ` (${formatClock(t.evidence_start_ms)})` : ""}`);
  }
  return lines.join("\n") + "\n";
}

export function download(filename: string, content: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

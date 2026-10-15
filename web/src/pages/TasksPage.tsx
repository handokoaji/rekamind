import { CheckSquare, ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { EmptyState, ErrorState, Skeleton } from "../components/ui/Feedback";
import { useAuth } from "../hooks/auth";
import { useAllTasks } from "../hooks/queries";
import { cn } from "../lib/cn";
import { formatDay, formatMinutes } from "../lib/format";
import { t } from "../lib/i18n";
import { priorityLabel, taskStatusLabel } from "../lib/strings";
import type { TaskStatus } from "../lib/types";

const tabs: TaskStatus[] = ["confirmed", "suggested", "rejected"];

export function TasksPage() {
  const { canAdmin } = useAuth();
  const [all, setAll] = useState(false);
  const { data, error, isLoading, refetch } = useAllTasks(canAdmin && all ? "all" : "mine");
  const [tab, setTab] = useState<TaskStatus>("confirmed");
  const shown = data?.filter((task) => task.status === tab) ?? [];
  const count = (s: TaskStatus) => data?.filter((task) => task.status === s).length ?? 0;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{t("Task")}</h1>
        <p className="mt-1 text-sm text-muted">{t("Task dari semua rapat. Hanya yang sudah Anda konfirmasi yang siap diteruskan ke sistem task manager.")}</p>
      </div>
      {canAdmin && (
        <label className="flex w-fit items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-[var(--primary)]" checked={all} onChange={(e) => setAll(e.target.checked)} /> {t("Tampilkan task semua pengguna")}</label>)}
      <div role="tablist" aria-label={t("Status task")} className="flex gap-1.5">
        {tabs.map((s) => (
          <button key={s} role="tab" aria-selected={tab === s} onClick={() => setTab(s)}
            className={cn("rounded-full px-3 py-1.5 text-sm font-medium", tab === s ? "bg-primary text-primary-fg" : "border border-border bg-card text-muted hover:text-fg")}>
            {taskStatusLabel[s]} <span className="tabular-nums">({count(s)})</span>
          </button>
        ))}
      </div>
      {isLoading ? <Skeleton className="h-40" /> : error ? <Card><ErrorState error={error} onRetry={() => void refetch()} /></Card> : shown.length === 0 ? (
        <Card><EmptyState icon={<CheckSquare className="size-6" />} title={tab === "suggested" ? t("Tidak ada task yang menunggu tinjauan") : t("Belum ada task di sini")}>
          {tab === "confirmed" ? t("Buka sebuah rapat, tinjau task yang diusulkan, lalu konfirmasi.") : t("Task dari rapat yang sudah diproses akan muncul di sini.")}
        </EmptyState></Card>
      ) : (
        <ul className="flex flex-col gap-2">
          {shown.map((task) => (
            <li key={task.id}>
              <Card className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4">
                <div className="min-w-0 flex-1 basis-64">
                  <p className="font-medium">{task.title}</p>
                  <Link to={`/rapat/${task.meeting_id}?tab=task`} className="mt-0.5 inline-flex items-center gap-1 text-xs text-muted hover:text-primary">
                    {task.meeting_title} <ExternalLink className="size-3" aria-hidden />
                  </Link>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
                  {task.assignee_name && <span>{t("PIC:")} <b className="font-medium text-fg">{task.assignee_name}</b></span>}
                  {task.deadline && <span>· {formatDay(task.deadline)}{task.deadline_approximate && ` ${t("(perkiraan)")}`}</span>}
                  {task.estimate_minutes && <span>· {formatMinutes(task.estimate_minutes)}</span>}
                </div>
                <Badge tone={task.priority === "high" ? "danger" : task.priority === "medium" ? "warning" : "neutral"}>{priorityLabel[task.priority]}</Badge>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

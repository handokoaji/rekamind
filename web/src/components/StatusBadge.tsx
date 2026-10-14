import { AlertCircle, CheckCircle2, ClipboardCheck, Clock, Loader2, Mic, PlayCircle } from "lucide-react";
import { statusLabel } from "../lib/strings";
import type { MeetingStatus } from "../lib/types";
import { Badge, type Tone } from "./ui/Badge";

const map: Record<MeetingStatus, { tone: Tone; icon: React.ReactNode }> = {
  recording: { tone: "danger", icon: <Mic className="size-3" /> },
  recorded: { tone: "neutral", icon: <PlayCircle className="size-3" /> },
  queued: { tone: "info", icon: <Clock className="size-3" /> },
  processing: { tone: "info", icon: <Loader2 className="size-3 animate-spin" /> },
  review: { tone: "warning", icon: <ClipboardCheck className="size-3" /> },
  done: { tone: "success", icon: <CheckCircle2 className="size-3" /> },
  failed: { tone: "danger", icon: <AlertCircle className="size-3" /> },
};

/** Status is always icon + text, never colour alone. */
export function StatusBadge({ status }: { status: MeetingStatus }) {
  const { tone, icon } = map[status];
  return <Badge tone={tone} icon={icon}>{statusLabel[status]}</Badge>;
}

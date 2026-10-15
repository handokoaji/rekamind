export type MeetingStatus = "recording" | "recorded" | "queued" | "processing" | "review" | "done" | "failed";
export type TaskStatus = "suggested" | "confirmed" | "rejected";
export type Priority = "low" | "medium" | "high";
export type Source = "mic" | "speaker";

export interface JobBrief { id: string; status: string; stage: string | null; progress: number }
export interface Meeting {
  id: string; title: string; status: MeetingStatus; language: string;
  started_at: string; ended_at: string | null; error: string | null; job: JobBrief | null;
  owner_email: string | null;
}
export interface Participant { id: string; label: string; name: string | null; is_local_user: boolean }
export interface Segment { id: number; participant_id: string | null; source: Source; start_ms: number; end_ms: number; text: string }
export interface MinutePoint { time: string | null; start_ms: number; point: string }
export interface Summary { overview: string; decisions: string[]; minutes: MinutePoint[] }
export interface Task {
  id: string; meeting_id: string; title: string; description: string;
  assignee_name: string | null; assignee_participant_id: string | null;
  deadline_text: string | null; deadline: string | null; deadline_approximate: boolean;
  estimate_minutes: number | null; priority: Priority; confidence: number;
  evidence_start_ms: number | null; evidence_quote: string; status: TaskStatus;
}
export interface TaskWithMeeting extends Task { meeting_title: string }
export interface MeetingDetail extends Meeting {
  participants: Participant[]; segments: Segment[]; summary: Summary | null; tasks: Task[];
}
export interface Capabilities { processing_ready: boolean; engines: Record<string, string>; timezone?: string; timezone_label?: string }
export interface TaskPatch {
  title?: string; description?: string; assignee_participant_id?: string | null; assignee_name?: string | null;
  deadline?: string | null; estimate_minutes?: number | null; priority?: Priority; status?: TaskStatus;
}

export type Role = "user" | "superadmin";
export interface Me { id: string; email: string; name: string | null; picture: string | null; role: Role; auth_mode: "google" | "local_token" | "none" }
export interface AdminUser {
  id: string; email: string; name: string | null; role: Role; disabled: boolean;
  invited: boolean; last_login_at: string | null; meetings: number;
}
export type Scope = "mine" | "all";

export type IntegrationKind = "webhook" | "github" | "gitlab";
export interface Integration { id: string; kind: IntegrationKind; name: string; config: Record<string, unknown>; has_secret: boolean; enabled: boolean }
export interface IntegrationStatus { available: boolean; reason: string | null; allow_private: boolean }
export interface PushResult { task_id: string; title: string; status: "created" | "updated" | "unchanged" | "failed"; url: string | null; error: string | null }
export interface TaskLinkInfo { task_id: string; integration_id: string; integration: string; external_id: string | null; url: string | null; state: "synced" | "failed"; error: string | null }
export type ExportFormat = "docx" | "md" | "json";


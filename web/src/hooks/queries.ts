import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { MeetingDetail, Scope, TaskPatch } from "../lib/types";

const ACTIVE = new Set(["queued", "processing"]);

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 15_000, retry: false });

export const useCapabilities = () => useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities, staleTime: 60_000 });

/** Polls only while something is actually being processed, so an idle page makes no requests. */
export const useMeetings = (q: string, status: string, scope: Scope = "mine") =>
  useQuery({
    queryKey: ["meetings", q, status, scope],
    queryFn: () => api.meetings(q, status, scope),
    refetchInterval: (query) => (query.state.data?.some((m) => m.job || ACTIVE.has(m.status)) ? 2_000 : false),
    placeholderData: (prev) => prev,
  });

export const useMeeting = (id: string) =>
  useQuery({
    queryKey: ["meeting", id],
    queryFn: () => api.meeting(id),
    refetchInterval: (query) => (query.state.data && ACTIVE.has(query.state.data.status) ? 2_000 : false),
  });

export const useAllTasks = (scope: Scope = "mine") => useQuery({ queryKey: ["tasks", scope], queryFn: () => api.tasks(undefined, scope) });

export function useInvalidate() {
  const qc = useQueryClient();
  return () => Promise.all([
    qc.invalidateQueries({ queryKey: ["meetings"] }),
    qc.invalidateQueries({ queryKey: ["meeting"] }),
    qc.invalidateQueries({ queryKey: ["tasks"] }),
  ]);
}

export function useProcessMeeting() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (id: string) => api.process(id), onSettled: invalidate });
}

/** Task edits apply instantly in the UI and roll back with the server's message if rejected. */
export function usePatchTask(meetingId: string) {
  const qc = useQueryClient();
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: TaskPatch }) => api.patchTask(id, patch),
    onMutate: async ({ id, patch }) => {
      await qc.cancelQueries({ queryKey: ["meeting", meetingId] });
      const prev = qc.getQueryData<MeetingDetail>(["meeting", meetingId]);
      if (prev) {
        qc.setQueryData<MeetingDetail>(["meeting", meetingId], {
          ...prev,
          tasks: prev.tasks.map((t) => (t.id === id ? { ...t, ...patch, deadline_approximate: "deadline" in patch ? false : t.deadline_approximate } : t)),
        });
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => ctx?.prev && qc.setQueryData(["meeting", meetingId], ctx.prev),
    onSettled: invalidate,
  });
}

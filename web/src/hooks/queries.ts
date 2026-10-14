import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "../lib/api";
import type { MeetingDetail, Scope, TaskPatch } from "../lib/types";

const ACTIVE = new Set(["queued", "processing"]);

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 15_000, retry: false });

export const useCapabilities = () => useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities, staleTime: 60_000 });

/** Polls only while something is actually being processed, so an idle page makes no requests. */
export const MEETINGS_PAGE = 50;

/** Newest first, a page at a time ("Tampilkan lebih banyak"). Polls only while something is being
 *  processed, so an idle page makes no requests. */
export const useMeetings = (q: string, status: string, scope: Scope = "mine") => {
  const query = useInfiniteQuery({
    queryKey: ["meetings", q, status, scope],
    queryFn: ({ pageParam }) => api.meetings(q, status, scope, pageParam, MEETINGS_PAGE),
    initialPageParam: 0,
    getNextPageParam: (last, all) => (last.length === MEETINGS_PAGE ? all.length * MEETINGS_PAGE : undefined),
    refetchInterval: (qr) => (qr.state.data?.pages.some((pg) => pg.some((m) => m.job || ACTIVE.has(m.status))) ? 2_000 : false),
    placeholderData: (prev) => prev,
  });
  const data = useMemo(() => query.data?.pages.flat(), [query.data]);
  return { ...query, data };
};

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
  return useMutation({ mutationFn: (v: string | { id: string; stage: "all" | "extract" }) => (typeof v === "string" ? api.process(v) : api.process(v.id, v.stage)), onSettled: invalidate });
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

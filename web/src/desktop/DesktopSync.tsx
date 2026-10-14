import { onlineManager, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useBackendReady } from "./backend";
import { useRecorder } from "./useRecorder";

/** Keeps the data views honest around a recording.
 *  - While recording the local backend is deliberately off (nothing heavy may run during a meeting),
 *    so queries are paused instead of failing: the list stays on screen, with no error pill.
 *  - When recording ends the backend is brought back and everything is refetched, so the meeting
 *    that was just uploaded appears without the user having to do anything. */
export function DesktopSync() {
  const { state } = useRecorder();
  const { retry } = useBackendReady();
  const qc = useQueryClient();
  const prev = useRef(state?.phase);
  const phase = state?.phase;

  useEffect(() => {
    const was = prev.current;
    prev.current = phase;
    if (phase === "recording") { onlineManager.setOnline(false); return; }
    onlineManager.setOnline(true);
    if (was === "recording") retry();                       // bring the backend back for the upload
    if (was === "recording" || was === "uploading") {
      void qc.invalidateQueries();                           // meeting list, tasks, health: all stale now
    }
  }, [phase, qc, retry]);

  return null;
}

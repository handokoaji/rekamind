import { X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";
import { formatClock } from "../lib/format";
import { t } from "../lib/i18n";
import type { Source } from "../lib/types";

interface Now { meetingId: string; source: Source; label: string }
interface Ctx { now: Now | null; ms: number; play: (n: Now, startMs: number) => void; close: () => void }
const PlayerCtx = createContext<Ctx | null>(null);
export const usePlayer = () => {
  const c = useContext(PlayerCtx);
  if (!c) throw new Error("usePlayer must be used inside PlayerProvider");
  return c;
};

/** One audio element for the whole app: clicking any timestamp or piece of evidence jumps
 *  straight to that moment, which is the fastest way to verify what the AI wrote. */
export function PlayerProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [now, setNow] = useState<Now | null>(null);
  const [ms, setMs] = useState(0);

  const loaded = useRef<{ key: string; url: string } | null>(null);

  const play = useCallback((n: Now, startMs: number) => {
    const el = audio.current;
    if (!el) return;
    const seekAndPlay = () => { el.currentTime = startMs / 1000; void el.play().catch(() => undefined); };
    const key = `${n.meetingId}/${n.source}`;
    setNow(n);
    if (loaded.current?.key === key) { seekAndPlay(); return; }
    api.fetchAudio(n.meetingId, n.source).then((blob) => {
      if (loaded.current) URL.revokeObjectURL(loaded.current.url);
      const url = URL.createObjectURL(blob);
      loaded.current = { key, url };
      el.src = url;
      el.addEventListener("loadedmetadata", seekAndPlay, { once: true });
      el.load();
    }).catch((e: unknown) => {
      setNow(null);
      toast.error(e instanceof Error ? e.message : t("Audio tidak bisa diputar."));
    });
  }, []);
  const close = useCallback(() => { audio.current?.pause(); setNow(null); setMs(0); }, []);
  const value = useMemo(() => ({ now, ms, play, close }), [now, ms, play, close]);

  return (
    <PlayerCtx.Provider value={value}>
      {children}
      <div hidden={!now} className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-card/95 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-2.5">
          <div className="min-w-0 text-sm">
            <p className="truncate font-medium">{now?.label}</p>
            <p className="text-xs text-muted tabular-nums">{formatClock(ms)}</p>
          </div>
          <audio ref={audio} controls preload="none" className="h-9 flex-1" aria-label={t("Pemutar audio rapat")}
            onTimeUpdate={(e) => setMs(e.currentTarget.currentTime * 1000)} />
          <button onClick={close} aria-label={t("Tutup pemutar")} className="rounded-lg p-2 text-muted hover:bg-primary-soft hover:text-fg"><X className="size-4" /></button>
        </div>
      </div>
    </PlayerCtx.Provider>
  );
}

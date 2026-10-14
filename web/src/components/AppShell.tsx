import { CheckSquare, FileAudio, Settings, Users, WifiOff } from "lucide-react";
import { Suspense, useEffect, useRef } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../hooks/auth";
import { useHealth } from "../hooks/queries";
import { UserMenu } from "./UserMenu";
import { cn } from "../lib/cn";
import { useBackendReady } from "../desktop/backend";
import { isDesktop } from "../desktop/bridge";
import { RecorderBar } from "../desktop/RecorderBar";
import { useDesktopRecording } from "../desktop/useRecorder";
import { ErrorState, Spinner } from "./ui/Feedback";
import { Button } from "./ui/Button";
import { Card } from "./ui/Card";

const nav = [
  { to: "/", label: "Rapat", icon: FileAudio, end: true },
  { to: "/task", label: "Task", icon: CheckSquare },
  { to: "/pengaturan", label: "Pengaturan", icon: Settings },
];

function ServerStatus() {
  const { isError, refetch, isFetching } = useHealth();
  const backend = useBackendReady();
  const recording = useDesktopRecording();
  // A local backend is switched off on purpose while recording and after idling: that is not an
  // error. Bring it back quietly instead of showing a red alarm.
  const quiet = isDesktop() && backend.mode === "local";
  // At most one restart per few seconds. Without the limit, "restart -> status flips -> effect runs
  // again while health still reads 'down'" looped ~140 times a second for the first 15 s after start.
  const lastRestart = useRef(0);
  useEffect(() => {
    if (isError && quiet && !recording && backend.status === "ready" && Date.now() - lastRestart.current > 5_000) {
      lastRestart.current = Date.now();
      backend.retry();
    }
  }, [isError, quiet, recording, backend]);
  const installing = !!backend.error?.startsWith("Pemasangan mesin");
  if (!isError || (quiet && (recording || installing || backend.status === "starting"))) return null; // connected is the normal state: say nothing
  return (
    <button onClick={() => void refetch()} disabled={isFetching}
      className="flex items-center gap-2 rounded-full bg-danger-soft px-3 py-1 text-xs font-medium text-danger">
      <WifiOff className="size-3.5" aria-hidden /> Server tidak terjangkau · {isFetching ? "mencoba…" : "coba lagi"}
    </button>
  );
}

/** Desktop + local mode: the processing service is started on demand, so show that, not an error. */
function Content() {
  const { status, error, retry, everReady } = useBackendReady();
  const onSettings = useLocation().pathname === "/pengaturan";
  const page = <Suspense fallback={<Spinner />}><Outlet /></Suspense>;
  // After the first successful start, never replace the page (it holds the recorder card and the
  // upload progress); a restart is just a quiet banner.
  if (status === "ready" || onSettings || everReady) {
    return (
      <>
        {status === "starting" && everReady && !onSettings && <p role="status" className="mb-4 flex items-center gap-2 text-sm text-muted"><span className="size-3 animate-spin rounded-full border-2 border-border border-t-primary" aria-hidden /> Menyalakan layanan pemrosesan lokal…</p>}
        {page}
      </>
    );
  }
  if (status === "starting") return <Spinner label="Menyalakan layanan pemrosesan lokal…" />;
  return (
    <Card>
      <ErrorState error={new Error(error ?? "Layanan lokal tidak bisa dinyalakan.")} onRetry={retry} />
      <div className="flex justify-center pb-8"><Link to="/pengaturan"><Button>Buka pengaturan</Button></Link></div>
    </Card>
  );
}

export function AppShell() {
  const { canAdmin } = useAuth();
  const items = canAdmin ? [...nav.slice(0, 2), { to: "/admin", label: "Pengguna", icon: Users }, nav[2]!] : nav;
  return (
    <div className="min-h-screen pb-24">
      <a href="#utama" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-card focus:px-3 focus:py-2">
        Lewati ke konten
      </a>
      {isDesktop() && <RecorderBar />}
      <header className="sticky top-0 z-20 border-b border-border bg-bg/85 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3">
          <NavLink to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-fg" aria-hidden>
              <span className="size-3 rounded-full border-[3px] border-current" />
            </span>
            Rekamind
          </NavLink>
          <nav aria-label="Utama" className="flex gap-1">
            {items.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end}
                className={({ isActive }) => cn("flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                  isActive ? "bg-primary-soft text-primary" : "text-muted hover:text-fg")}>
                <Icon className="size-4" aria-hidden /> <span className="hidden sm:inline">{label}</span>
                <span className="sm:hidden sr-only">{label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3"><ServerStatus /><UserMenu /></div>
        </div>
      </header>
      <main id="utama" className="mx-auto max-w-5xl px-4 py-8">
        {/* The header stays put while a page chunk loads; only the content area shows progress. */}
        <Content />
      </main>
    </div>
  );
}

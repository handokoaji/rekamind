import { CheckSquare, FileAudio, Settings, WifiOff } from "lucide-react";
import { Suspense } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useHealth } from "../hooks/queries";
import { cn } from "../lib/cn";
import { Spinner } from "./ui/Feedback";

const nav = [
  { to: "/", label: "Rapat", icon: FileAudio, end: true },
  { to: "/task", label: "Task", icon: CheckSquare },
  { to: "/pengaturan", label: "Pengaturan", icon: Settings },
];

function ServerStatus() {
  const { isError, refetch, isFetching } = useHealth();
  if (!isError) return null; // connected is the normal state: say nothing
  return (
    <button onClick={() => void refetch()} disabled={isFetching}
      className="flex items-center gap-2 rounded-full bg-danger-soft px-3 py-1 text-xs font-medium text-danger">
      <WifiOff className="size-3.5" aria-hidden /> Server tidak terjangkau · {isFetching ? "mencoba…" : "coba lagi"}
    </button>
  );
}

export function AppShell() {
  return (
    <div className="min-h-screen pb-24">
      <a href="#utama" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-card focus:px-3 focus:py-2">
        Lewati ke konten
      </a>
      <header className="sticky top-0 z-20 border-b border-border bg-bg/85 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3">
          <NavLink to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-fg" aria-hidden>
              <span className="size-3 rounded-full border-[3px] border-current" />
            </span>
            Rekamind
          </NavLink>
          <nav aria-label="Utama" className="flex gap-1">
            {nav.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end}
                className={({ isActive }) => cn("flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                  isActive ? "bg-primary-soft text-primary" : "text-muted hover:text-fg")}>
                <Icon className="size-4" aria-hidden /> <span className="hidden sm:inline">{label}</span>
                <span className="sm:hidden sr-only">{label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto"><ServerStatus /></div>
        </div>
      </header>
      <main id="utama" className="mx-auto max-w-5xl px-4 py-8">
        {/* The header stays put while a page chunk loads; only the content area shows progress. */}
        <Suspense fallback={<Spinner />}><Outlet /></Suspense>
      </main>
    </div>
  );
}

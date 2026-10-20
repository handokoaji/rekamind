import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { AppShell } from "./components/AppShell";
import { LoginScreen } from "./components/LoginScreen";
import { Spinner } from "./components/ui/Feedback";
import { ErrorState } from "./components/ui/Feedback";
import { AuthProvider, useAuthState } from "./hooks/auth";
import { PlayerProvider } from "./components/Player";
import { I18nProvider, t } from "./lib/i18n";
import { TimeZoneProvider } from "./hooks/timezone";
import { BackendProvider } from "./desktop/backend";
import { isDesktop } from "./desktop/bridge";
import { DesktopRecovery } from "./desktop/DesktopRecovery";
import { DesktopSync } from "./desktop/DesktopSync";
import { RecorderProvider } from "./desktop/useRecorder";
import { MeetingsPage } from "./pages/MeetingsPage";
import { NotFound } from "./pages/NotFound";

// Only the list page is needed to paint the first screen; everything else loads on navigation.
const AdminPage = lazy(() => import("./pages/AdminPage").then((m) => ({ default: m.AdminPage })));
const MeetingDetailPage = lazy(() => import("./pages/MeetingDetailPage").then((m) => ({ default: m.MeetingDetailPage })));
const TasksPage = lazy(() => import("./pages/TasksPage").then((m) => ({ default: m.TasksPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));

const client = new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: true } } });

/** Desktop-only providers; a plain browser never loads or runs any of it. */
function Desktop({ children }: { children: React.ReactNode }) {
  return isDesktop() ? <BackendProvider><RecorderProvider><DesktopSync />{children}</RecorderProvider></BackendProvider> : <>{children}</>;
}

/** Nothing below this point renders for someone who is not signed in. */
function Authenticated({ children }: { children: React.ReactNode }) {
  const auth = useAuthState();
  if (auth.status === "loading") return <Spinner label={t("Memeriksa sesi…")} />;
  if (auth.status === "signed-out") return <LoginScreen />;
  if (auth.status === "error") return isDesktop() ? <DesktopRecovery error={auth.error} /> : <ErrorState error={auth.error} onRetry={() => window.location.reload()} />;
  return <AuthProvider me={auth.me}>{children}</AuthProvider>;
}

export default function App() {
  return (
    <QueryClientProvider client={client}>
      <I18nProvider>
      <BrowserRouter>
        <Desktop>
        <Authenticated>
        <TimeZoneProvider>
        <PlayerProvider>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<MeetingsPage />} />
              <Route path="rapat/:id" element={<MeetingDetailPage />} />
              <Route path="task" element={<TasksPage />} />
              <Route path="admin" element={<AdminPage />} />
              <Route path="pengaturan" element={<SettingsPage />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </PlayerProvider>
        </TimeZoneProvider>
        </Authenticated>
        </Desktop>
      </BrowserRouter>
      </I18nProvider>
      <Toaster position="bottom-right" closeButton toastOptions={{ style: { fontFamily: "inherit" } }} />
    </QueryClientProvider>
  );
}

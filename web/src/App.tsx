import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { AppShell } from "./components/AppShell";
import { PlayerProvider } from "./components/Player";
import { BackendProvider } from "./desktop/backend";
import { isDesktop } from "./desktop/bridge";
import { DesktopSync } from "./desktop/DesktopSync";
import { RecorderProvider } from "./desktop/useRecorder";
import { MeetingsPage } from "./pages/MeetingsPage";
import { NotFound } from "./pages/NotFound";

// Only the list page is needed to paint the first screen; everything else loads on navigation.
const MeetingDetailPage = lazy(() => import("./pages/MeetingDetailPage").then((m) => ({ default: m.MeetingDetailPage })));
const TasksPage = lazy(() => import("./pages/TasksPage").then((m) => ({ default: m.TasksPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));

const client = new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: true } } });

/** Desktop-only providers; a plain browser never loads or runs any of it. */
function Desktop({ children }: { children: React.ReactNode }) {
  return isDesktop() ? <BackendProvider><RecorderProvider><DesktopSync />{children}</RecorderProvider></BackendProvider> : <>{children}</>;
}

export default function App() {
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <Desktop>
        <PlayerProvider>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<MeetingsPage />} />
              <Route path="rapat/:id" element={<MeetingDetailPage />} />
              <Route path="task" element={<TasksPage />} />
              <Route path="pengaturan" element={<SettingsPage />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </PlayerProvider>
        </Desktop>
      </BrowserRouter>
      <Toaster position="bottom-right" closeButton toastOptions={{ style: { fontFamily: "inherit" } }} />
    </QueryClientProvider>
  );
}

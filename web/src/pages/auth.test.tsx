import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoginScreen } from "../components/LoginScreen";
import { UserMenu } from "../components/UserMenu";
import { AuthProvider, useAuthState } from "../hooks/auth";
import { ApiError, onUnauthorized } from "../lib/api";
import type { AdminUser, Me } from "../lib/types";
import { AdminPage } from "./AdminPage";
import { MeetingsPage } from "./MeetingsPage";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
const user = (o: Partial<Me> = {}): Me => ({ id: "u1", email: "alice@kantor.id", name: "Alice", picture: null, role: "user", auth_mode: "google", ...o });
const boss = user({ id: "u0", email: "boss@kantor.id", name: "Boss", role: "superadmin" });
const adminUser = (o: Partial<AdminUser> = {}): AdminUser => ({ id: "u1", email: "alice@kantor.id", name: "Alice", role: "user", disabled: false, invited: false, last_login_at: "2026-10-14T01:00:00Z", meetings: 3, ...o });

function renderWith(me: Me, ui: React.ReactNode, route = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><AuthProvider me={me}><MemoryRouter initialEntries={[route]}><Routes><Route path="/" element={ui} /><Route path="/admin" element={ui} /></Routes></MemoryRouter></AuthProvider></QueryClientProvider>);
}
afterEach(() => vi.unstubAllGlobals());

describe("login screen", () => {
  it("offers Google sign-in that remembers where the user was going, and states the privacy rule", () => {
    window.history.pushState({}, "", "/rapat/abc?tab=task");
    render(<LoginScreen />);
    const link = screen.getByRole("link", { name: /Masuk dengan Google/ });
    expect(link).toHaveAttribute("href", "/auth/login?redirect=%2Frapat%2Fabc%3Ftab%3Dtask");
    expect(screen.getByText(/hanya bisa melihat rapat milik Anda/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Rekamind");
  });
});

describe("session handling", () => {
  function Probe() { const a = useAuthState(); return <p>{a.status}</p>; }
  const probe = () => render(<QueryClientProvider client={new QueryClient()}><Probe /></QueryClientProvider>);

  it("a 401 from /api/me means 'show the login screen', not an error page", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "Silakan masuk." }, 401)));
    probe();
    expect(await screen.findByText("signed-out")).toBeInTheDocument();
  });
  it("a server failure is an error, not a login prompt", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "x" }, 500)));
    probe();
    expect(await screen.findByText("error")).toBeInTheDocument();
  });
  it("a signed-in user is ready", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(user())));
    probe();
    expect(await screen.findByText("ready")).toBeInTheDocument();
  });
  it("any 401 anywhere re-asks who is signed in (a session that expired while the page was open)", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string) => { calls.push(String(url)); return Promise.resolve(json(calls.length === 1 ? user() : { detail: "Sesi berakhir" }, calls.length === 1 ? 200 : 401)); }));
    probe();
    await screen.findByText("ready");
    const { api } = await import("../lib/api");
    await expect(api.meetings()).rejects.toBeInstanceOf(ApiError);
    expect(await screen.findByText("signed-out")).toBeInTheDocument();
  });
  it("being signed out asks /api/me exactly once, not in a loop", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ detail: "Silakan masuk." }, 401));
    vi.stubGlobal("fetch", fetchMock);
    probe();
    await screen.findByText("signed-out");
    await new Promise((r) => setTimeout(r, 300));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it("unauthorized listeners can be removed", () => {
    const f = vi.fn();
    const off = onUnauthorized(f);
    off();
    expect(f).not.toHaveBeenCalled();
  });
});

describe("user menu", () => {
  it("shows who is signed in, marks super admins, and signs out", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    Object.defineProperty(window, "location", { value: { ...window.location, assign: vi.fn() }, writable: true });
    renderWith(boss, <UserMenu />);
    expect(screen.getAllByText("boss@kantor.id").length).toBeGreaterThan(0);
    expect(screen.getByText("Super admin")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Keluar" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/auth/logout", expect.objectContaining({ method: "POST" })));
  });
  it("is absent in single-user modes where there is nobody to sign out", () => {
    renderWith(user({ auth_mode: "local_token" }), <UserMenu />);
    expect(screen.queryByRole("button", { name: "Keluar" })).toBeNull();
  });
});

describe("admin page", () => {
  const users = [adminUser(), adminUser({ id: "u2", email: "tamu@luar.org", name: null, invited: true, last_login_at: null, meetings: 0 }), adminUser({ id: "u3", email: "bob@kantor.id", name: "Bob", disabled: true })];
  const handler = (calls: { method: string; url: string; body?: unknown }[]) =>
    vi.fn((url: string, init?: RequestInit) => {
      calls.push({ method: init?.method ?? "GET", url: String(url), body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (init?.method === "PATCH") return Promise.resolve(json({ ...users[0], role: "superadmin" }));
      if (init?.method === "POST") return Promise.resolve(json(adminUser({ id: "u9", email: "baru@kantor.id" }), 201));
      return Promise.resolve(json(users));
    });

  it("lists users with their state in words, and invites by email", async () => {
    const calls: { method: string; url: string; body?: unknown }[] = [];
    vi.stubGlobal("fetch", handler(calls));
    renderWith(boss, <AdminPage />, "/admin");
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Diundang")).toBeInTheDocument();
    expect(screen.getByText("Belum pernah masuk")).toBeInTheDocument();
    expect(screen.getByText("Nonaktif")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Undang dengan email Google"), "baru@kantor.id");
    await userEvent.click(screen.getByRole("button", { name: "Undang" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({ email: "baru@kantor.id", role: "user" }));
  });

  it("asks before promoting someone, and says what the role means", async () => {
    const calls: { method: string; url: string; body?: unknown }[] = [];
    vi.stubGlobal("fetch", handler(calls));
    renderWith(boss, <AdminPage />, "/admin");
    await screen.findByText("Alice");
    await userEvent.click(screen.getAllByRole("button", { name: "Jadikan super admin" })[0]!);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/melakukan apa pun/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PATCH")).toBe(false); // nothing changed yet
    await userEvent.click(within(dialog).getByRole("button", { name: "Ya, lanjutkan" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ role: "superadmin" }));
  });

  it("is closed to ordinary users", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderWith(user(), <AdminPage />, "/admin");
    expect(screen.queryByText("Pengguna")).toBeNull();
  });
});

describe("meetings page scope (super admin)", () => {
  it("a super admin can switch to everyone's meetings and sees whose they are; others get no switch", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      urls.push(String(url));
      if (String(url).includes("capabilities")) return Promise.resolve(json({ processing_ready: true, engines: {} }));
      return Promise.resolve(json([{ id: "a".repeat(32), title: "Rapat Alice", status: "review", language: "id", started_at: "2026-10-14T01:00:00Z", ended_at: null, error: null, job: null, owner_email: "alice@kantor.id" }]));
    }));
    const { unmount } = renderWith(boss, <MeetingsPage />);
    await screen.findByText("Rapat Alice");
    expect(screen.queryByText("alice@kantor.id")).toBeNull(); // own view: no owner clutter
    await userEvent.click(screen.getByRole("button", { name: "Semua pengguna" }));
    expect(await screen.findByText("alice@kantor.id")).toBeInTheDocument();
    expect(urls.some((u) => u.includes("scope=all"))).toBe(true);
    unmount();
    renderWith(user(), <MeetingsPage />);
    await screen.findByText("Rapat Alice");
    expect(screen.queryByRole("group", { name: "Cakupan rapat" })).toBeNull();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const bridge = vi.hoisted(() => ({ login: vi.fn(), logout: vi.fn(), settings: vi.fn(), ensureBackend: vi.fn() }));
vi.mock("./bridge", () => ({ desktop: bridge, isDesktop: () => true, onChanged: () => Promise.resolve(() => undefined) }));
const toast = vi.hoisted(() => ({ warning: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

import { LoginScreen } from "../components/LoginScreen";
import { useAuthState } from "../hooks/auth";
import { BackendProvider } from "./backend";

function ui() {
  const qc = new QueryClient();
  const spy = vi.spyOn(qc, "invalidateQueries");
  render(<QueryClientProvider client={qc}><LoginScreen /></QueryClientProvider>);
  return spy;
}
beforeEach(() => { Object.values(bridge).forEach((f) => f.mockReset()); toast.warning.mockReset(); });
afterEach(() => vi.unstubAllGlobals());

describe("desktop sign-in", () => {
  it("uses the shell's browser flow (a button, not a cookie redirect) and re-asks who is signed in", async () => {
    bridge.login.mockResolvedValue({ email: "a@kantor.id", token: "rks_x", remembered: true });
    const spy = ui();
    expect(screen.queryByRole("link")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Masuk dengan Google/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ["me"] }));
    expect(toast.warning).not.toHaveBeenCalled();
  });
  it("warns when the OS refused to remember the login", async () => {
    bridge.login.mockResolvedValue({ email: "a@kantor.id", token: "rks_x", remembered: false });
    ui();
    await userEvent.click(screen.getByRole("button", { name: /Masuk dengan Google/ }));
    await waitFor(() => expect(toast.warning).toHaveBeenCalled());
  });
  it("shows the failure and lets the user try again", async () => {
    bridge.login.mockRejectedValueOnce(new Error("Waktu login habis."));
    ui();
    await userEvent.click(screen.getByRole("button", { name: /Masuk dengan Google/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Waktu login habis.");
    expect(screen.getByRole("button", { name: /Masuk dengan Google/ })).toBeEnabled();
  });
});

describe("session check in the desktop app", () => {
  const view = { settings: { mode: "remote" }, server_url: "http://127.0.0.1:1", auth_token: "tok", recordings_dir: "", hotkey_error: null };
  function Probe() { const a = useAuthState(); return <p>{a.status}</p>; }
  const mount = () => render(<QueryClientProvider client={new QueryClient()}><BackendProvider><Probe /></BackendProvider></QueryClientProvider>);

  it("does not ask the server who is signed in until the shell has the backend up (no spurious 'cannot connect')", async () => {
    let up!: () => void;
    bridge.settings.mockResolvedValue(view);
    bridge.ensureBackend.mockReturnValue(new Promise<void>((r) => { up = r; }));
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "u", email: "a@b.c", name: "A", picture: null, role: "superadmin", auth_mode: "local" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    mount();
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText("loading")).toBeInTheDocument();
    up();
    expect(await screen.findByText("ready")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((fetchMock.mock.calls[0]![1] as RequestInit).headers).toMatchObject({ authorization: "Bearer tok" });
  });
  it("the local backend serves only this person: no identity request, and the app opens even while the backend is off (recording)", async () => {
    bridge.settings.mockResolvedValue({ ...view, settings: { mode: "local" } });
    bridge.ensureBackend.mockRejectedValue(new Error("Perekaman sedang berjalan."));
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    mount();
    expect(await screen.findByText("ready")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("a remote server that cannot be reached is reported as such, not as a login problem", async () => {
    bridge.settings.mockResolvedValue(view);
    bridge.ensureBackend.mockRejectedValue(new Error("Layanan lokal tidak mau menyala."));
    vi.stubGlobal("fetch", vi.fn());
    mount();
    expect(await screen.findByText("error")).toBeInTheDocument();
  });
});

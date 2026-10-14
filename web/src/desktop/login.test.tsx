import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const bridge = vi.hoisted(() => ({ login: vi.fn(), logout: vi.fn() }));
vi.mock("./bridge", () => ({ desktop: bridge, isDesktop: () => true, onChanged: () => Promise.resolve(() => undefined) }));
const toast = vi.hoisted(() => ({ warning: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

import { LoginScreen } from "../components/LoginScreen";

function ui() {
  const qc = new QueryClient();
  const spy = vi.spyOn(qc, "invalidateQueries");
  render(<QueryClientProvider client={qc}><LoginScreen /></QueryClientProvider>);
  return spy;
}
beforeEach(() => { bridge.login.mockReset(); toast.warning.mockReset(); });

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

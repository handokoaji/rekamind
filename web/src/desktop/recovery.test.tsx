import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const bridge = vi.hoisted(() => ({ settings: vi.fn(), saveSettings: vi.fn() }));
vi.mock("./bridge", () => ({ desktop: bridge }));
vi.mock("./DesktopSettings", () => ({ DesktopSettings: () => <p>panel pengaturan desktop</p> }));

import { DesktopRecovery } from "./DesktopRecovery";

const remote = { settings: { mode: "remote", server: "https://rekamind.example.com", language: "id" } };
beforeEach(() => { bridge.settings.mockReset().mockResolvedValue(remote); bridge.saveSettings.mockReset().mockResolvedValue(undefined); });

describe("desktop recovery screen", () => {
  it("shows the connection error and lets the user reach the server settings without signing in", async () => {
    render(<DesktopRecovery error={new Error("Tidak dapat terhubung ke server.")} reload={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Tidak dapat terhubung ke server.");
    expect(screen.queryByText("panel pengaturan desktop")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Ubah pengaturan server" }));
    expect(screen.getByText("panel pengaturan desktop")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sembunyikan pengaturan" }));
    expect(screen.queryByText("panel pengaturan desktop")).toBeNull();
    expect(screen.getByRole("button", { name: "Coba lagi" })).toBeInTheDocument();
  });
  it("switches back to local mode in one click, keeping every other setting, then reloads", async () => {
    const reload = vi.fn();
    render(<DesktopRecovery error={new Error("x")} reload={reload} />);
    await userEvent.click(screen.getByRole("button", { name: "Pakai mode lokal" }));
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(bridge.saveSettings).toHaveBeenCalledWith({ ...remote.settings, mode: "local" });
  });
  it("says why it could not switch (e.g. a recording is running) and stays usable", async () => {
    bridge.saveSettings.mockRejectedValue(new Error("Hentikan rekaman dulu sebelum mengubah pengaturan."));
    const reload = vi.fn();
    render(<DesktopRecovery error={new Error("x")} reload={reload} />);
    await userEvent.click(screen.getByRole("button", { name: "Pakai mode lokal" }));
    expect(await screen.findByText("Hentikan rekaman dulu sebelum mengubah pengaturan.")).toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Pakai mode lokal" })).toBeEnabled();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UpdateInfo } from "./types";

const bridge = vi.hoisted(() => ({ checkUpdate: vi.fn(), installUpdate: vi.fn() }));
vi.mock("./bridge", () => ({ desktop: bridge, isDesktop: () => true }));

import { UpdateBanner } from "./UpdateBanner";

const info = (o: Partial<UpdateInfo> = {}): UpdateInfo => ({
  version: "0.4.0-beta.5", html_url: "https://github.com/handokoaji/rekamind/releases/tag/v0.4.0-beta.5",
  installer_url: "https://github.com/handokoaji/rekamind/releases/download/v0.4.0-beta.5/Rekamind-Windows-x64-setup.exe", sums_url: "https://x/SHA256SUMS.txt", ...o,
});
const show = () => render(<QueryClientProvider client={new QueryClient()}><UpdateBanner /></QueryClientProvider>);
beforeEach(() => { bridge.checkUpdate.mockReset(); bridge.installUpdate.mockReset().mockResolvedValue(undefined); });

describe("update banner", () => {
  it("announces the new version and installs it with one click", async () => {
    bridge.checkUpdate.mockResolvedValue(info());
    show();
    expect(await screen.findByText("Versi 0.4.0-beta.5 tersedia")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Perbarui sekarang" }));
    expect(bridge.installUpdate).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Mengunduh pembaruan…" })).toBeDisabled();
  });
  it("stays quiet when already up to date", async () => {
    bridge.checkUpdate.mockResolvedValue(null);
    show();
    await waitFor(() => expect(bridge.checkUpdate).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByText(/tersedia/)).toBeNull();
  });
  it("shows why the update was refused (e.g. a recording is running) and lets the user try again", async () => {
    bridge.checkUpdate.mockResolvedValue(info());
    bridge.installUpdate.mockRejectedValue(new Error("Selesaikan rekaman dulu."));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Perbarui sekarang" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Selesaikan rekaman dulu.");
    expect(screen.getByRole("button", { name: "Perbarui sekarang" })).toBeEnabled();
  });
  it("offers the release page where the app cannot install itself, and hides on 'Nanti'", async () => {
    bridge.checkUpdate.mockResolvedValue(info({ installer_url: null }));
    show();
    expect(await screen.findByRole("button", { name: "Buka halaman rilis" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Nanti" }));
    expect(screen.queryByText(/tersedia/)).toBeNull();
  });
});

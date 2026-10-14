import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../hooks/auth";
import type { Me } from "../lib/types";
import { MeetingsPage } from "./MeetingsPage";

const me: Me = { id: "u1", email: "alice@kantor.id", name: "Alice", picture: null, role: "user", auth_mode: "google" };

const meeting = (o = {}) => ({ id: "a".repeat(32), title: "Rapat vendor", status: "review", language: "id", started_at: "2026-10-14T01:00:00Z", ended_at: null, error: null, job: null, owner_email: "alice@kantor.id", ...o });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function setup(handler: (url: string) => Response | Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(handler(String(url)))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><AuthProvider me={me}><MemoryRouter><MeetingsPage /></MemoryRouter></AuthProvider></QueryClientProvider>);
}
afterEach(() => vi.unstubAllGlobals());

describe("MeetingsPage", () => {
  it("lists meetings with a text status (never colour alone)", async () => {
    setup((u) => (u.includes("/capabilities") ? json({ processing_ready: true, engines: {} }) : json([meeting()])));
    expect(await screen.findByText("Rapat vendor")).toBeInTheDocument();
    expect(screen.getAllByText("Perlu ditinjau").length).toBeGreaterThan(0);
  });

  it("pages through a long history instead of silently showing only the newest 50", async () => {
    const urls: string[] = [];
    const page = (from: number, n: number) => Array.from({ length: n }, (_, i) => meeting({ id: String(from + i).padStart(32, "0"), title: `Rapat ${from + i}` }));
    setup((u) => {
      urls.push(u);
      if (u.includes("/capabilities")) return json({ processing_ready: true, engines: {} });
      return json(u.includes("offset=50") ? page(50, 7) : page(0, 50));
    });
    expect(await screen.findByText("Rapat 0")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Tampilkan lebih banyak" }));
    expect(await screen.findByText("Rapat 56")).toBeInTheDocument();
    expect(screen.getByText("Rapat 0")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tampilkan lebih banyak" })).toBeNull(); // 7 < 50: that was the last page
    expect(urls.some((u) => u.includes("offset=50"))).toBe(true);
  });

  it("explains what to do when there are no meetings yet", async () => {
    setup((u) => (u.includes("/capabilities") ? json({ processing_ready: false, engines: {} }) : json([])));
    expect(await screen.findByRole("heading", { name: "Belum ada rapat" })).toBeInTheDocument();
    expect(screen.getByText(/aplikasi desktop/)).toBeInTheDocument();
  });

  it("shows the failure reason and a retry, not a blank page", async () => {
    let fail = true;
    setup((u) => {
      if (u.includes("/capabilities")) return json({ processing_ready: true, engines: {} });
      if (fail) return json({ detail: "Server mengalami masalah." }, 500);
      return json([meeting()]);
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Server mengalami masalah");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Coba lagi" }));
    await waitFor(() => expect(screen.getByText("Rapat vendor")).toBeInTheDocument());
  });

  it("offers Proses only when the server can actually process", async () => {
    const { unmount } = setup((u) => (u.includes("/capabilities") ? json({ processing_ready: false, engines: {} }) : json([meeting({ status: "recorded" })])));
    await screen.findByText("Rapat vendor");
    expect(screen.queryByRole("button", { name: /Proses/ })).toBeNull();
    unmount();
    setup((u) => (u.includes("/capabilities") ? json({ processing_ready: true, engines: {} }) : json([meeting({ status: "recorded" })])));
    expect(await screen.findByRole("button", { name: /Proses/ })).toBeInTheDocument();
  });

  it("shows live progress with the current stage in plain words", async () => {
    setup((u) => (u.includes("/capabilities") ? json({ processing_ready: true, engines: {} }) : json([meeting({ status: "processing", job: { id: "j", status: "running", stage: "diarizing", progress: 55 } })])));
    expect(await screen.findByText("Mengenali pembicara")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "55");
  });
});

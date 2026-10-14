import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PlayerProvider } from "../components/Player";
import { MeetingDetailPage } from "./MeetingDetailPage";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
const ID = "a".repeat(32);
const seg = (i: number) => ({ id: i, participant_id: "p1", source: "speaker", start_ms: i * 1000, end_ms: i * 1000 + 900, text: `kalimat ${i}` });
const meeting = (o = {}) => ({
  id: ID, title: "Rapat panjang", status: "review", language: "id", started_at: "2026-10-14T01:00:00Z", ended_at: null, error: null, job: null,
  owner_email: null, participants: [{ id: "p1", label: "SPEAKER_00", name: null, is_local_user: false }], segments: [seg(0), seg(1)], summary: null, tasks: [], ...o,
});

function show(handler: (url: string, init?: RequestInit) => Response) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => { calls.push(`${init?.method ?? "GET"} ${url}`); return Promise.resolve(handler(String(url), init)); }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <PlayerProvider><MemoryRouter initialEntries={[`/rapat/${ID}`]}><Routes><Route path="rapat/:id" element={<MeetingDetailPage />} /></Routes></MemoryRouter></PlayerProvider></QueryClientProvider>);
  return calls;
}
afterEach(() => vi.unstubAllGlobals());

describe("a meeting whose summary could not be made", () => {
  it("keeps the transcript, says why, and offers to redo only the summary", async () => {
    const calls = show((u) => u.includes("/capabilities") ? json({ processing_ready: true, engines: {} })
      : u.includes("/process") ? json({ id: "j", status: "queued" }, 202)
      : json(meeting({ error: 'Ringkasan dan task belum dibuat: LLM mengembalikan 413: Request too large. Transkrip tersimpan.' })));
    expect(await screen.findByText(/Ringkasan dan task belum dibuat: LLM mengembalikan 413/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Buat ulang ringkasan" }));
    await waitFor(() => expect(calls.some((c) => c.startsWith("POST") && c.includes("/process?stage=extract"))).toBe(true));
  });

  it("does not offer it when a summary exists (a speaker warning only informs)", async () => {
    show((u) => u.includes("/capabilities") ? json({ processing_ready: true, engines: {} })
      : json(meeting({ error: "Pemisah pembicara gagal (X); semua suara komputer ditandai satu pembicara.", summary: { overview: "ok", decisions: [], minutes: [] } })));
    expect(await screen.findByText(/Pemisah pembicara gagal/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Buat ulang ringkasan" })).toBeNull();
  });
});

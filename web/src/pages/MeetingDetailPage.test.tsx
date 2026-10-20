import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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


describe("speaker count hint", () => {
  it("saves the number the user picks, then processes the meeting again", async () => {
    const calls = show((u, init) => u.includes("/capabilities") ? json({ processing_ready: true, engines: {} })
      : u.includes("/process") ? json({ id: "j", status: "queued" }, 202)
      : init?.method === "PATCH" ? json(meeting({ num_speakers: 3 }))
      : json(meeting({ summary: { overview: "ok", decisions: [], minutes: [] } })));
    await userEvent.click(await screen.findByRole("tab", { name: "Pembicara" }));
    expect(await screen.findByText(/Terdeteksi 1 pembicara/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Jumlah pembicara sebenarnya"), "3");
    await userEvent.click(screen.getByRole("button", { name: "Pisahkan ulang" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Pisahkan ulang" }));
    await waitFor(() => expect(calls.some((c) => c.startsWith("POST") && c.includes("/process"))).toBe(true));
    const patch = calls.findIndex((c) => c.startsWith("PATCH"));
    expect(patch).toBeGreaterThan(-1);
    expect(patch).toBeLessThan(calls.findIndex((c) => c.startsWith("POST") && c.includes("/process"))); // hint first
  });
});

describe("the summary tab", () => {
  const withSummary = (summary: object) => show((u) => u.includes("/capabilities") ? json({ processing_ready: true, engines: {} }) : json(meeting({ summary })));

  it("shows the key points and decisions first, then the detail of the meeting", async () => {
    withSummary({ overview: "Gambaran rapat", key_points: ["Anggaran naik 10%"], decisions: ["Vendor A dipakai"], minutes: [{ time: "00:05", start_ms: 5000, point: "Bahas anggaran" }] });
    const headings = (await screen.findAllByRole("heading", { level: 3 })).map((h) => h.textContent);
    expect(headings).toEqual(["Ringkasan", "Poin penting", "Keputusan", "Jalannya rapat"]);
    expect(screen.getByText("Anggaran naik 10%")).toBeInTheDocument();
    expect(screen.getByText("Vendor A dipakai")).toBeInTheDocument();
  });

  it("says so when there are no key points or decisions, instead of hiding the sections", async () => {
    withSummary({ overview: "Obrolan santai", key_points: [], decisions: [], minutes: [] });
    expect(await screen.findByText("Tidak ada poin penting yang tercatat.")).toBeInTheDocument();
    expect(screen.getByText("Tidak ada keputusan yang tercatat.")).toBeInTheDocument();
  });

  it("lists every topic with where it ended up, so a subject that was dropped is not lost", async () => {
    withSummary({
      overview: "Rapat pimpinan", key_points: [], decisions: [], minutes: [],
      topics: [
        { title: "Anggaran 2027", summary: "Diputuskan naik 10%.", status: "decided", times: ["03:10", "21:40"], follow_up: null },
        { title: "Kontrak vendor", summary: "Belum jelas siapa pemegangnya.", status: "open", times: ["12:00"], follow_up: "Tentukan penanggung jawab" },
        { title: "Parkir gedung", summary: "Disebut sekilas, lalu pindah topik.", status: "dropped", times: ["15:30"], follow_up: "Bahas lagi bila perlu" },
      ],
    });
    expect(await screen.findByRole("heading", { name: "Topik yang dibahas" })).toBeInTheDocument();
    expect(screen.getByText("Diputuskan")).toBeInTheDocument();
    expect(screen.getByText("Masih terbuka")).toBeInTheDocument();
    expect(screen.getByText("Tidak dilanjutkan")).toBeInTheDocument();
    expect(screen.getByText("03:10, 21:40")).toBeInTheDocument(); // it came back later in the meeting
    expect(screen.getByText("Tentukan penanggung jawab")).toBeInTheDocument();
  });

  it("copes with a server that does not send key points yet", async () => {
    withSummary({ overview: "Dari server lama", decisions: [], minutes: [] });
    expect(await screen.findByText("Tidak ada poin penting yang tercatat.")).toBeInTheDocument();
  });
});

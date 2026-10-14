import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, normalizeBackendUrl } from "./api";
import { tasksToJson, tasksToMarkdown } from "./export";
import { fileTitle, formatClock, formatDay, formatMinutes } from "./format";
import type { MeetingDetail, Task } from "./types";

describe("format", () => {
  it("formats clocks and durations", () => {
    expect(formatClock(330_000)).toBe("05:30");
    expect(formatClock(3_723_000)).toBe("1:02:03");
    expect(formatMinutes(150)).toBe("2 jam 30 menit");
    expect(formatMinutes(120)).toBe("2 jam");
    expect(formatMinutes(45)).toBe("45 menit");
  });
  it("never shifts a calendar date by timezone", () => {
    expect(formatDay("2026-10-23")).toContain("23");
    expect(formatDay("2026-01-01")).toContain("2026");
  });
  it("derives a title from a file name", () => {
    expect(fileTitle("rapat_vendor-minggu_ini.m4a")).toBe("rapat vendor minggu ini");
  });
});

describe("backend URL", () => {
  it("accepts only http(s) origins and strips paths", () => {
    expect(normalizeBackendUrl("https://rekamind.kantor.id/foo?x=1")).toBe("https://rekamind.kantor.id");
    expect(normalizeBackendUrl("")).toBe("");
    for (const bad of ["javascript:alert(1)", "file:///etc/passwd", "ftp://x", "bukan url"]) expect(normalizeBackendUrl(bad)).toBeNull();
  });
});

describe("api errors", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("turns a network failure into an actionable message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fail")));
    await expect(api.meetings()).rejects.toMatchObject({ status: 0, message: expect.stringContaining("Pengaturan") });
  });
  it("surfaces the server's own message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Rapat tidak ditemukan" }), { status: 404 })));
    await expect(api.meeting("x")).rejects.toEqual(new ApiError(404, "Rapat tidak ditemukan"));
  });
  it("does not leak raw validation arrays to the user", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [{ loc: ["body"], msg: "x" }] }), { status: 422 })));
    await expect(api.createMeeting({ title: "", language: "id" })).rejects.toThrow(/Isian belum valid/);
  });
});

const task = (o: Partial<Task>): Task => ({
  id: "t1", meeting_id: "m", title: "Kirim penawaran", description: "", assignee_name: "Budi", assignee_participant_id: "p1",
  deadline_text: "Jumat depan", deadline: "2026-10-23", deadline_approximate: false, estimate_minutes: 120, priority: "high",
  confidence: 0.9, evidence_start_ms: 65_000, evidence_quote: "Budi kirim penawaran", status: "confirmed", ...o,
});
const meeting = { id: "m", title: "Rapat", started_at: "2026-10-14T01:00:00Z", participants: [{ id: "p1", label: "SPEAKER_00", name: "Budi Santoso", is_local_user: false }] } as MeetingDetail;

describe("task export (the contract the task manager will consume)", () => {
  it("emits a versioned, stable JSON shape with the resolved PIC name", () => {
    const j = JSON.parse(tasksToJson(meeting, [task({})]));
    expect(j.schema).toBe("rekamind.tasks/v1");
    expect(j.tasks[0]).toMatchObject({ assignee: "Budi Santoso", deadline: "2026-10-23", estimate_minutes: 120, priority: "high", evidence: { start_ms: 65000 } });
  });
  it("falls back to the spoken name when no participant is linked and flags approximate deadlines", () => {
    const j = JSON.parse(tasksToJson(meeting, [task({ assignee_participant_id: null, deadline_approximate: true })]));
    expect(j.tasks[0].assignee).toBe("Budi");
    expect(j.tasks[0].deadline_is_approximate).toBe(true);
  });
  it("renders readable markdown", () => {
    const md = tasksToMarkdown(meeting, [task({})]);
    expect(md).toContain("- [ ] **Kirim penawaran**");
    expect(md).toContain("PIC: Budi Santoso");
    expect(md).toContain("Estimasi: 2 jam");
  });
});

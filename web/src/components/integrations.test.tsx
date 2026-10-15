import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Task } from "../lib/types";
import { ExportDialog } from "./ExportDialog";
import { IntegrationsCard } from "./IntegrationsCard";
import { PushPanel } from "./PushPanel";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "content-type": "application/json" } });
const GH = { id: "i1", kind: "github", name: "Repo tim", config: { repo: "kantor/proyek" }, has_secret: true, enabled: true };
const task = (id: string, title: string): Task => ({ id, meeting_id: "m", title, description: "", assignee_name: null, assignee_participant_id: null, deadline_text: null, deadline: null, deadline_approximate: false, estimate_minutes: null, priority: "medium", confidence: 0.9, evidence_start_ms: null, evidence_quote: "", status: "confirmed", created_at: "", updated_at: "" } as unknown as Task);

function wrap(ui: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}
function stub(handler: (method: string, url: string, body: unknown) => Response) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    const call = { method: init?.method ?? "GET", url: String(url), body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    return Promise.resolve(handler(call.method, call.url, call.body));
  }));
  return calls;
}
afterEach(() => vi.unstubAllGlobals());

describe("export dialog", () => {
  it("asks the server for exactly what was chosen and saves the file under the server's name", async () => {
    const created: Blob[] = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: (b: Blob) => { created.push(b); return "blob:x"; }, revokeObjectURL: () => undefined }));
    const calls = stub(() => new Response("# rapat", { status: 200, headers: { "content-disposition": 'attachment; filename="rekamind-20261015-rapat.md"' } }));
    wrap(<ExportDialog meetingId="m1" open onOpenChange={() => undefined} />);
    await userEvent.click(screen.getByRole("radio", { name: /Markdown/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /transkrip lengkap/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /belum dikonfirmasi/ }));
    await userEvent.click(screen.getByRole("button", { name: /Unduh/ }));
    await waitFor(() => expect(created.length).toBe(1));
    expect(calls[0]!.url).toContain("/api/meetings/m1/export?");
    expect(calls[0]!.url).toContain("format=md");
    expect(calls[0]!.url).toContain("transcript=false");
    expect(calls[0]!.url).toContain("tasks=all");
  });
  it("defaults to Word with the transcript and only confirmed tasks", async () => {
    wrap(<ExportDialog meetingId="m1" open onOpenChange={() => undefined} />);
    expect(screen.getByRole("radio", { name: /Word/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /transkrip lengkap/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /belum dikonfirmasi/ })).not.toBeChecked();
  });
});

describe("push panel", () => {
  it("stays out of the way when nothing is configured and nothing is possible", async () => {
    stub((_m, u) => (u.includes("/status") ? json({ available: false, reason: "x", allow_private: false }) : json([])));
    wrap(<PushPanel meetingId="m" confirmed={[task("t1", "A")]} />);
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText(/Kirim task terkonfirmasi/)).toBeNull();
  });
  it("points to the settings when integrations are possible but none exist", async () => {
    stub((_m, u) => (u.includes("/status") ? json({ available: true, reason: null, allow_private: true }) : json([])));
    wrap(<PushPanel meetingId="m" confirmed={[task("t1", "A")]} />);
    expect(await screen.findByRole("link", { name: "Atur integrasi" })).toHaveAttribute("href", "/pengaturan");
  });
  it("sends only on click, shows each failure with its reason, and links what was created", async () => {
    const calls = stub((m, u) => {
      if (u.includes("/integrations/status")) return json({ available: true, reason: null, allow_private: false });
      if (u.endsWith("/api/integrations")) return json([GH]);
      if (u.includes("/links")) return json([]);
      if (m === "POST" && u.includes("/push")) return json({ integration: "Repo tim", results: [
        { task_id: "t1", title: "Kirim laporan", status: "created", url: "https://github.com/kantor/proyek/issues/7", error: null },
        { task_id: "t2", title: "Siapkan draft", status: "failed", url: null, error: "GitHub: HTTP 401. Token ditolak atau kedaluwarsa." }] });
      return json({});
    });
    wrap(<PushPanel meetingId="m" confirmed={[task("t1", "Kirim laporan"), task("t2", "Siapkan draft")]} />);
    const send = await screen.findByRole("button", { name: /Kirim 2 task/ });
    expect(calls.some((c) => c.method === "POST")).toBe(false); // opening the tab sent nothing
    await userEvent.click(send);
    expect(await screen.findByRole("alert")).toHaveTextContent("Token ditolak");
    const push = calls.find((c) => c.method === "POST")!;
    expect(push.url).toContain("/meetings/m/push");
    expect(push.body).toMatchObject({ integration_id: "i1" });
  });
});

describe("integrations settings", () => {
  it("explains why integrations are off on a shared server without a key", async () => {
    stub((_m, u) => (u.includes("/status") ? json({ available: false, reason: "Integrasi butuh REKAMIND_SECRET_KEY", allow_private: false }) : json([])));
    wrap(<IntegrationsCard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("REKAMIND_SECRET_KEY");
    expect(screen.queryByRole("button", { name: /Tambah integrasi/ })).toBeNull();
  });
  it("builds the GitHub configuration, including the name-to-login map, and never echoes the token back", async () => {
    const calls = stub((m, u) => {
      if (u.includes("/status")) return json({ available: true, reason: null, allow_private: false });
      if (m === "POST") return json({ ...GH });
      return json([]);
    });
    wrap(<IntegrationsCard />);
    await userEvent.click(await screen.findByRole("button", { name: /Tambah integrasi/ }));
    await userEvent.type(screen.getByLabelText("Repositori"), "kantor/proyek");
    await userEvent.type(screen.getByLabelText(/Pemetaan PIC/), "Budi = budi-gh");
    await userEvent.type(screen.getByLabelText("Token akses"), "ghp_secret");
    expect(screen.getByLabelText("Token akses")).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: "Simpan" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ kind: "github", secret: "ghp_secret", config: { repo: "kantor/proyek", labels: ["rekamind"], assignees: { Budi: "budi-gh" } } });
  });
  it("lists integrations with a connection test whose result is read aloud", async () => {
    stub((m, u) => {
      if (u.includes("/status")) return json({ available: true, reason: null, allow_private: false });
      if (u.includes("/test")) return json({ ok: false, message: "GitHub: HTTP 404. Repo/proyek tidak ditemukan" });
      if (m === "GET") return json([GH]);
      return json({});
    });
    wrap(<IntegrationsCard />);
    await userEvent.click(await screen.findByRole("button", { name: "Uji integrasi" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("tidak ditemukan");
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EngineState, SettingsView } from "./types";

const bridge = vi.hoisted(() => ({
  engines: vi.fn(), checkEngines: vi.fn(), installEngines: vi.fn(), warmupModel: vi.fn(), cancelEngines: vi.fn(),
  settings: vi.fn(), saveSettings: vi.fn(), setSecrets: vi.fn(),
}));
vi.mock("./bridge", () => ({ desktop: bridge, isDesktop: () => true, onChanged: () => Promise.resolve(() => undefined) }));
const handlers = vi.hoisted(() => ({} as Record<string, (e: { payload: unknown }) => void>));
vi.mock("@tauri-apps/api/event", () => ({ listen: (name: string, fn: (e: { payload: unknown }) => void) => { handlers[name] = fn; return Promise.resolve(() => undefined); } }));
vi.mock("./useRecorder", () => ({ useRecorder: () => ({ state: { phase: "idle" } }) }));

import { DesktopSettings } from "./DesktopSettings";
import { EnginesPanel, parseInstallProgress } from "./EnginesPanel";

const pack = (o: Partial<EngineState["pack"]> = {}): EngineState["pack"] => ({ pack_dir: "/data/engine-pack", asr: false, diarize: false, kind: null, python: "3.13", ...o });
const state = (o: Partial<EngineState> = {}): EngineState => ({ pack: pack(), job: { running: null, log: [], last_error: undefined }, ...o });
const view = (o: Partial<SettingsView> = {}): SettingsView => ({
  settings: { mode: "local", server: "", local_program: "auto", local_args: [], local_port: 8787, language: "id", local_user_name: "", auto_process: true, hotkey: "CmdOrCtrl+Alt+R",
    whisper_model: "large-v3", whisper_device: "auto", diarizer: "none", llm_base_url: "https://api.groq.com/openai/v1", llm_model: "m", glossary: "" },
  server_url: "http://127.0.0.1:8787", auth_token: "t", recordings_dir: "/r", hotkey_error: null, has_llm_key: false, has_hf_token: false, bundled_backend: true, backend_dir: "/d", ...o,
});
beforeEach(() => { Object.values(bridge).forEach((f) => f.mockReset().mockResolvedValue(undefined)); for (const k of Object.keys(handlers)) delete handlers[k]; });

describe("engine pack panel", () => {
  it("offers installation for CPU or NVIDIA when nothing is installed, and says recording still works", async () => {
    bridge.engines.mockResolvedValue(state());
    render(<EnginesPanel recording={false} whisperModel="large-v3" />);
    expect(await screen.findByText("Belum dipasang")).toBeInTheDocument();
    expect(screen.getByText(/Rekaman tetap bisa dilakukan/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /pemisah pembicara/i }));
    await userEvent.click(screen.getByRole("button", { name: /untuk NVIDIA GPU/ }));
    expect(bridge.installEngines).toHaveBeenCalledWith("cuda", true);
  });
  it("offers Intel GPU (OpenVINO), recommends it when an Intel GPU is present, and installs the openvino kind", async () => {
    bridge.engines.mockResolvedValue(state({ pack: pack({ gpus: [{ vendor: "intel", name: "Intel(R) Arc(TM) Graphics" }] }) }));
    render(<EnginesPanel recording={false} whisperModel="large-v3" />);
    expect(await screen.findByText(/GPU Intel terdeteksi di komputer ini/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /untuk Intel GPU/ }));
    expect(bridge.installEngines).toHaveBeenCalledWith("openvino", false);
  });
  it("does not nag about Intel when an NVIDIA GPU is present", async () => {
    bridge.engines.mockResolvedValue(state({ pack: pack({ gpus: [{ vendor: "intel", name: "UHD" }, { vendor: "nvidia", name: "RTX" }] }) }));
    render(<EnginesPanel recording={false} whisperModel="large-v3" />);
    await screen.findByText("Belum dipasang");
    expect(screen.queryByText(/GPU Intel terdeteksi di komputer ini/)).toBeNull();
  });
  it("labels an OpenVINO pack and reports the Intel GPU on 'Uji mesin'", async () => {
    bridge.engines.mockResolvedValue(state({ pack: pack({ asr: true, kind: "openvino" }) }));
    bridge.checkEngines.mockResolvedValue({ ok: true, error: null, cuda_devices: 0, openvino: "2025.3", ov_devices: ["CPU", "GPU"], intel_gpu: true });
    render(<EnginesPanel recording={false} whisperModel="large-v3" />);
    expect(await screen.findByText(/Terpasang · Intel GPU/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Uji mesin/ }));
    expect(await screen.findByText(/Mesin berfungsi \(OpenVINO 2025.3\)/)).toBeInTheDocument();
    expect(screen.getByText(/GPU Intel terdeteksi\./)).toBeInTheDocument();
    expect(screen.getByText(/Perangkat: CPU, GPU/)).toBeInTheDocument();
  });
  it("offers AMD GPU (Vulkan), recommends it for an AMD GPU, and installs the vulkan kind", async () => {
    bridge.engines.mockResolvedValue(state({ pack: pack({ gpus: [{ vendor: "amd", name: "AMD Radeon(TM) 860M Graphics" }] }) }));
    render(<EnginesPanel recording={false} whisperModel="large-v3" />);
    expect(await screen.findByText(/GPU AMD terdeteksi di komputer ini/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /untuk GPU AMD \(Vulkan\)/ }));
    expect(bridge.installEngines).toHaveBeenCalledWith("vulkan", false);
  });
  it("reports the Vulkan device on 'Uji mesin', and asks for the model first when none is cached", async () => {
    bridge.engines.mockResolvedValue(state({ pack: pack({ asr: true, kind: "vulkan" }) }));
    bridge.checkEngines.mockResolvedValueOnce({ ok: true, error: null, cuda_devices: 0, whispercpp: "v1.9.5", vulkan_devices: [], gpu: false, model_cached: null });
    render(<EnginesPanel recording={false} whisperModel="large-v3" />);
    expect(await screen.findByText(/Terpasang · GPU \(Vulkan\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Uji mesin/ }));
    expect(await screen.findByText(/Program terpasang; unduh model dulu/)).toBeInTheDocument();
    bridge.checkEngines.mockResolvedValueOnce({ ok: true, error: null, cuda_devices: 0, whispercpp: "v1.9.5", vulkan_devices: ["AMD Radeon(TM) 860M Graphics"], gpu: true, model_cached: "ggml-large-v3-q5_0.bin" });
    await userEvent.click(screen.getByRole("button", { name: /Uji mesin/ }));
    expect(await screen.findByText(/GPU terdeteksi: AMD Radeon\(TM\) 860M Graphics/)).toBeInTheDocument();
  });
  it("cannot start an install while recording", async () => {
    bridge.engines.mockResolvedValue(state());
    render(<EnginesPanel recording={true} whisperModel="large-v3" />);
    expect(await screen.findByRole("button", { name: /untuk CPU/ })).toBeDisabled();
  });
  it("replays the buffered log when reopened mid-install and can cancel", async () => {
    bridge.engines.mockResolvedValue(state({ job: { running: "install cpu", log: ["Collecting torch", "Downloading torch-2.13.whl"], last_error: undefined } }));
    render(<EnginesPanel recording={false} whisperModel="large-v3" />);
    expect(await screen.findByRole("status")).toHaveTextContent("Memasang mesin");
    expect(screen.queryByLabelText("Keluaran pemasangan")).toBeNull(); // log is hidden until asked for
    await userEvent.click(screen.getByRole("button", { name: "Tampilkan log" }));
    expect(await screen.findByLabelText("Keluaran pemasangan")).toHaveTextContent("Downloading torch-2.13.whl");
    await userEvent.click(screen.getByRole("button", { name: "Batalkan" }));
    expect(bridge.cancelEngines).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /untuk CPU/ })).toBeNull(); // nothing can be started twice
  });
  it("shows live output, and after a successful install verifies the engines and reports the GPU", async () => {
    bridge.engines.mockResolvedValue(state());
    bridge.checkEngines.mockResolvedValue({ ok: true, error: null, cuda_devices: 1, faster_whisper: "1.2.1" });
    render(<EnginesPanel recording={false} whisperModel="large-v3" />);
    await screen.findByText("Belum dipasang");
    await waitFor(() => expect(handlers["engines://line"]).toBeDefined());
    handlers["engines://line"]!({ payload: "Collecting faster-whisper" });
    await userEvent.click(await screen.findByRole("button", { name: "Tampilkan log" }));
    expect(await screen.findByLabelText("Keluaran pemasangan")).toHaveTextContent("Collecting faster-whisper");
    bridge.engines.mockResolvedValue(state({ pack: pack({ asr: true, kind: "cuda" }) }));
    handlers["engines://done"]!({ payload: null });
    expect(await screen.findByText(/GPU NVIDIA terdeteksi: 1/)).toBeInTheDocument();
    expect(screen.getByText(/Terpasang · NVIDIA GPU/)).toBeInTheDocument();
  });
  it("a broken install is reported as such, not as success", async () => {
    bridge.engines.mockResolvedValue(state({ pack: pack({ asr: true, kind: "cpu" }) }));
    bridge.checkEngines.mockResolvedValue({ ok: false, error: "ImportError: libcudnn", cuda_devices: 0 });
    render(<EnginesPanel recording={false} whisperModel="large-v3" />);
    await userEvent.click(await screen.findByRole("button", { name: /Uji mesin/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("libcudnn");
  });
  it("shows why the last install failed", async () => {
    bridge.engines.mockResolvedValue(state({ job: { running: null, log: [], last_error: "gagal (exit 1): no matching distribution" } }));
    render(<EnginesPanel recording={false} whisperModel="large-v3" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("no matching distribution");
  });
});

describe("processing settings", () => {
  it("secrets are write-only: stored ones show a mask, new ones go to the credential store, never into the settings file", async () => {
    bridge.settings.mockResolvedValue(view({ has_llm_key: true }));
    bridge.engines.mockResolvedValue(state());
    bridge.saveSettings.mockResolvedValue(view({ has_llm_key: true, has_hf_token: true }));
    bridge.setSecrets.mockResolvedValue(view({ has_llm_key: true, has_hf_token: true }));
    render(<DesktopSettings />);
    const llm = await screen.findByLabelText("Kunci API ringkasan");
    expect(llm).toHaveValue("");
    expect(llm).toHaveAttribute("type", "password");
    expect(screen.getByText(/Sudah tersimpan di penyimpanan kredensial/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Token Hugging Face"), "hf_secret");
    await userEvent.click(screen.getByRole("button", { name: "Simpan" }));
    await waitFor(() => expect(bridge.setSecrets).toHaveBeenCalledWith({ hfToken: "hf_secret" }));
    expect(JSON.stringify(bridge.saveSettings.mock.calls)).not.toContain("hf_secret");
  });
  it("hides processing options when a remote server does the work", async () => {
    bridge.settings.mockResolvedValue(view({ settings: { ...view().settings, mode: "remote", server: "https://x.id" } }));
    render(<DesktopSettings />);
    await screen.findByText("Alamat server");
    expect(screen.queryByText("Mesin transkripsi")).toBeNull();
    expect(within(document.body).queryByLabelText("Model Whisper")).toBeNull();
  });
});

import { MemoryRouter } from "react-router-dom";
import { BackendProvider } from "./backend";
import { EngineSetupBanner } from "./EngineSetupBanner";

describe("first-run banner", () => {
  const show = (ready: boolean | undefined, mode: "local" | "remote") => {
    bridge.settings.mockResolvedValue(view({ settings: { ...view().settings, mode } }));
    (bridge as Record<string, unknown>).ensureBackend = vi.fn().mockResolvedValue(undefined);
    return render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><BackendProvider><EngineSetupBanner ready={ready} /></BackendProvider></MemoryRouter></QueryClientProvider>);
  };
  it("points a local, not-yet-ready machine to the installation, and says recording still works", async () => {
    show(false, "local");
    expect(await screen.findByText("Mesin transkripsi belum dipasang")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Pasang mesin" })).toHaveAttribute("href", "/pengaturan");
    expect(screen.getByText(/tetap bisa merekam/)).toBeInTheDocument();
  });
  it("stays quiet when ready, while unknown, or when a remote server does the processing", async () => {
    for (const [ready, mode] of [[true, "local"], [undefined, "local"], [false, "remote"]] as const) {
      const { unmount } = show(ready, mode);
      await new Promise((r) => setTimeout(r, 30));
      expect(screen.queryByText("Mesin transkripsi belum dipasang")).toBeNull();
      unmount();
    }
  });
});

describe("backend start", () => {
  it("re-checks server health once the backend answered (so the 'unreachable' pill clears without waiting 15 s)", async () => {
    bridge.settings.mockResolvedValue(view());
    (bridge as Record<string, unknown>).ensureBackend = vi.fn().mockResolvedValue(undefined);
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    render(<QueryClientProvider client={qc}><MemoryRouter><BackendProvider><p>x</p></BackendProvider></MemoryRouter></QueryClientProvider>);
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ["health"] }));
  });
});

describe("parseInstallProgress", () => {
  it("reads percent, size and speed from the installer's progress line", () => {
    expect(parseInstallProgress(["x", "  ... 123 / 700 MB (17%), 0.45 MB/s"])).toEqual({ pct: 17, doneMb: 123, totalMb: 700, speed: 0.45, stalled: false });
  });
  it("handles an unknown total, thousands separators, and a stall warning being the newest line", () => {
    expect(parseInstallProgress(["  ... 1,234 MB terunduh"])?.doneMb).toBe(1234);
    expect(parseInstallProgress(["  ... 5 / 9 MB (55%), 1.00 MB/s", "  ! Tidak ada kemajuan unduhan selama 60 dtk (5 dari 9 MB)."])?.stalled).toBe(true);
    expect(parseInstallProgress(["Rekamind 0.4.0, build fc5bd12"])).toBeNull();
  });
});

describe("install progress bar", () => {
  it("shows the download bar with its speed, and the stall warning, while the log stays hidden", async () => {
    bridge.engines.mockResolvedValue(state({ job: { running: "install cuda", log: ["  ... 123 / 700 MB (17%), 0.45 MB/s"], last_error: undefined } }));
    render(<EnginesPanel recording={false} whisperModel="large-v3" />);
    expect(await screen.findByRole("progressbar", { name: "Kemajuan unduhan" })).toHaveAttribute("aria-valuenow", "17");
    expect(screen.getByText(/123 dari 700 MB · 0\.45 MB\/s/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Keluaran pemasangan")).toBeNull();
  });
});

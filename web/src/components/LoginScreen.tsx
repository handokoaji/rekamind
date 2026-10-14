import { useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { desktop, isDesktop } from "../desktop/bridge";
import { getBackendUrl, setAuthToken } from "../lib/api";
import { Card } from "./ui/Card";

/** Google's own button guidelines: the "G" mark and plain wording, on a light surface. */
function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" className="size-5" aria-hidden>
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.2 5.3-4.6 7l7.2 5.6c4.3-3.9 7.1-9.7 7.1-17.1z" />
      <path fill="#FBBC05" d="M10.5 28.7c-.5-1.4-.8-2.9-.8-4.7s.3-3.3.8-4.7l-7.9-6.1C.9 16.4 0 20.1 0 24s.9 7.6 2.6 10.8l7.9-6.1z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.2-5.6c-2 1.4-4.6 2.2-8.7 2.2-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z" />
    </svg>
  );
}

const BTN = "flex h-11 w-full items-center justify-center gap-3 rounded-lg border border-border bg-white px-4 text-sm font-medium text-[#1f1f1f] shadow-sm transition-colors hover:bg-[#f6f7f9] disabled:opacity-70";

/** The desktop app has no cookie: it signs in through the system browser and keeps a token. */
function DesktopSignIn() {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setBusy(true); setError(null);
    try {
      const r = await desktop.login();
      setAuthToken(r.token);
      if (!r.remembered) toast.warning("Login berhasil, tetapi tidak bisa disimpan di penyimpanan kredensial sistem. Anda harus login lagi saat aplikasi dibuka berikutnya.");
      await qc.invalidateQueries({ queryKey: ["me"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login gagal.");
    } finally { setBusy(false); }
  };
  return (
    <>
      <button type="button" onClick={go} disabled={busy} aria-busy={busy} className={BTN}>
        {busy ? <Loader2 className="size-5 animate-spin" aria-hidden /> : <GoogleMark />}
        {busy ? "Menunggu login di browser…" : "Masuk dengan Google"}
      </button>
      {busy && <p className="text-xs text-muted" role="status">Selesaikan login di jendela browser yang terbuka. Batas waktu 5 menit.</p>}
      {error && <p className="text-sm text-danger" role="alert">{error}</p>}
    </>
  );
}

export function LoginScreen() {
  const here = window.location.pathname + window.location.search;
  const href = `${getBackendUrl()}/auth/login?redirect=${encodeURIComponent(here)}`;
  return (
    <main className="grid min-h-screen place-items-center px-4">
      <Card className="flex w-full max-w-sm flex-col items-center gap-6 p-8 text-center">
        <span className="grid size-12 place-items-center rounded-xl bg-primary text-primary-fg" aria-hidden>
          <span className="size-4 rounded-full border-[3px] border-current" />
        </span>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Rekamind</h1>
          <p className="mt-2 text-sm text-muted">Masuk untuk melihat rapat, transkrip, dan task Anda.</p>
        </div>
        {isDesktop() ? <DesktopSignIn /> : (
          <a href={href} className={BTN}>
            <GoogleMark /> Masuk dengan Google
          </a>
        )}
        <p className="flex items-start gap-2 text-left text-xs text-muted">
          <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
          Anda hanya bisa melihat rapat milik Anda sendiri. Kata sandi Google tidak pernah dikirim ke Rekamind.
        </p>
      </Card>
    </main>
  );
}

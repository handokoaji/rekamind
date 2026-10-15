import { Fragment, useSyncExternalStore, type ReactNode } from "react";
import { enComponents } from "./en.components";
import { enDesktop } from "./en.desktop";
import { enPages } from "./en.pages";

/**
 * Interface language. Indonesian is the source language: the code holds the Indonesian text and
 * `t(<teks Indonesia>)` returns it as is, or its English entry when English is selected. A missing
 * English entry falls back to the Indonesian text (a guard test fails the build for that).
 * Placeholders: t("Kirim {n} task", { n: 3 }).
 */
export type Lang = "id" | "en";
export const LANGS: { code: Lang; label: string }[] = [{ code: "id", label: "Indonesia" }, { code: "en", label: "English" }];

export const EN: Record<string, string> = { ...enComponents, ...enPages, ...enDesktop };

const KEY = "rekamind.lang";
function load(): Lang {
  try { const v = localStorage.getItem(KEY); if (v === "id" || v === "en") return v; } catch { /* private mode */ }
  return "id"; // the default is Indonesian regardless of browser language, by design
}
let current: Lang = load();
const listeners = new Set<() => void>();
if (typeof document !== "undefined") document.documentElement.lang = current;

export const getLang = (): Lang => current;
export function setLang(l: Lang): void {
  if (l === current) return;
  current = l;
  try { localStorage.setItem(KEY, l); } catch { /* ignore */ }
  if (typeof document !== "undefined") document.documentElement.lang = l;
  listeners.forEach((f) => f());
}
export const intlLocale = () => (current === "en" ? "en-GB" : "id-ID");

export function t(src: string, vars?: Record<string, string | number>): string {
  let out = current === "en" ? (EN[src] ?? src) : src;
  if (vars) out = out.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
  return out;
}

/** An object whose string values are translated on every read, so label tables need no call-site changes. */
export function translated<T extends Record<string, string>>(table: T): T {
  return new Proxy(table, { get: (o, k) => (typeof k === "string" && k in o ? t(o[k as keyof T] as string) : undefined) }) as T;
}

const subscribe = (f: () => void) => { listeners.add(f); return () => listeners.delete(f); };
export const useLang = (): Lang => useSyncExternalStore(subscribe, getLang, getLang);

/** Remounts the tree below on a language change: every plain t() call re-evaluates, no per-component plumbing. */
export function I18nProvider({ children }: { children: ReactNode }) {
  return <Fragment key={useLang()}>{children}</Fragment>;
}

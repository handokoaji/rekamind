import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { EN, I18nProvider, setLang, t, translated } from ".";
import { formatMinutes } from "../format";

afterEach(() => act(() => setLang("id")));

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) return sources(p);
    return /\.(ts|tsx)$/.test(f) && !/\.test\./.test(f) && !p.includes("/lib/i18n/") ? [p] : [];
  });
}

describe("i18n", () => {
  it("Indonesian is the default and returns the source text", () => {
    expect(t("Selesai")).toBe("Selesai");
    expect(t("Kirim {n} task", { n: 3 })).toBe("Kirim 3 task");
  });

  it("switches to English with placeholders, and falls back to the source for an unknown string", () => {
    EN["Contoh {n}"] = "Example {n}";
    setLang("en");
    expect(t("Contoh {n}", { n: 2 })).toBe("Example 2");
    expect(t("tidak ada di kamus")).toBe("tidak ada di kamus");
    delete EN["Contoh {n}"];
  });

  it("translated() label tables follow the current language", () => {
    EN["Siap diproses"] = "Ready to process";
    const labels = translated({ recorded: "Siap diproses" });
    expect(labels.recorded).toBe("Siap diproses");
    setLang("en");
    expect(labels.recorded).toBe("Ready to process");
  });

  it("the provider re-renders the tree when the language changes", () => {
    EN["Halo"] = "Hello";
    const Hi = () => <p>{t("Halo")}</p>;
    render(<I18nProvider><Hi /></I18nProvider>);
    expect(screen.getByText("Halo")).toBeInTheDocument();
    act(() => setLang("en"));
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("durations are phrased in the selected language", () => {
    expect(formatMinutes(150)).toBe("2 jam 30 menit");
    setLang("en");
    expect(formatMinutes(150)).toBe("2 h 30 min");
  });

  it("every literal passed to t() in the source has an English entry (no half-translated screens)", () => {
    const missing: string[] = [];
    const re = /\bt\(\s*(["'`])((?:\\.|(?!\1).)*)\1/gs;
    for (const file of sources(join(import.meta.dirname, "../.."))) {
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(re)) {
        const key = m[2]!.replace(/\\(["'`])/g, "$1");
        if (!(key in EN)) missing.push(`${file.split("/src/")[1]}: ${key}`);
      }
    }
    expect(missing).toEqual([]);
  });
});

it("every status/stage/priority label has an English entry", async () => {
  const { LABEL_SOURCES } = await import("../strings");
  expect(LABEL_SOURCES.filter((s) => !(s in EN))).toEqual([]);
});

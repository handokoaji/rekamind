import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeCard } from "./ThemeCard";

const root = document.documentElement;
const pressed = (name: string) => screen.getByRole("button", { name }).getAttribute("aria-pressed") === "true";

beforeEach(() => { localStorage.clear(); root.removeAttribute("data-theme"); });
afterEach(() => vi.restoreAllMocks());

describe("theme setting", () => {
  it("follows the system by default: nothing is set on the page", () => {
    render(<ThemeCard />);
    expect(pressed("Ikuti sistem")).toBe(true);
    expect(root.hasAttribute("data-theme")).toBe(false);
    expect(localStorage.getItem("rekamind.theme")).toBeNull();
  });

  it("applies and remembers an explicit choice, and going back to the system forgets it", async () => {
    render(<ThemeCard />);
    await userEvent.click(screen.getByRole("button", { name: "Gelap" }));
    expect(root.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("rekamind.theme")).toBe("dark");
    expect(pressed("Gelap")).toBe(true);

    await userEvent.click(screen.getByRole("button", { name: "Terang" }));
    expect(root.getAttribute("data-theme")).toBe("light");

    await userEvent.click(screen.getByRole("button", { name: "Ikuti sistem" }));
    expect(root.hasAttribute("data-theme")).toBe(false);
    expect(localStorage.getItem("rekamind.theme")).toBeNull();
  });

  it("opens on the remembered choice", () => {
    localStorage.setItem("rekamind.theme", "light");
    render(<ThemeCard />);
    expect(pressed("Terang")).toBe(true);
    expect(root.getAttribute("data-theme")).toBe("light");
  });

  it("ignores a value it does not know instead of breaking", () => {
    localStorage.setItem("rekamind.theme", "sepia");
    render(<ThemeCard />);
    expect(pressed("Ikuti sistem")).toBe(true);
  });

  it("still switches when the browser blocks storage (the choice just lasts this visit)", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    render(<ThemeCard />);
    await userEvent.click(screen.getByRole("button", { name: "Gelap" }));
    expect(root.getAttribute("data-theme")).toBe("dark");
  });
});

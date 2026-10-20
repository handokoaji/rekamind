import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const bridge = vi.hoisted(() => ({ openExternal: vi.fn(), desktopMode: false }));
vi.mock("../desktop/bridge", () => ({ desktop: bridge, isDesktop: () => bridge.desktopMode }));

import { ABOUT, APP_VERSION } from "../lib/about";
import { AboutCard } from "./AboutCard";

beforeEach(() => { bridge.desktopMode = false; bridge.openExternal.mockReset().mockResolvedValue(undefined); });

describe("about card", () => {
  it("names the author, the version and the licence, and links to the right places", () => {
    render(<AboutCard />);
    expect(screen.getByText(new RegExp(`Versi ${APP_VERSION.replace(/\./g, "\\.")}`))).toBeInTheDocument();
    expect(screen.getByText(/AGPL-3\.0-or-later/)).toBeInTheDocument();
    const href = (name: string) => screen.getByRole("link", { name }).getAttribute("href");
    expect(href("Rochmad Handoko Aji")).toBe("https://github.com/handokoaji");
    expect(href("Kode sumber")).toBe("https://github.com/handokoaji/rekamind");
    expect(href("Laporkan masalah")).toBe("https://github.com/handokoaji/rekamind/issues");
    expect(href("Instagram")).toBe("https://www.instagram.com/rhandokoaji/");
    expect(href("GitHub Sponsors")).toBe("https://github.com/sponsors/handokoaji");
    expect(href("Saweria")).toBe("https://saweria.co/handokoaji");
  });

  it("opens every link in a new tab without handing the page to the other site", () => {
    render(<AboutCard />);
    const links = screen.getAllByRole("link");
    expect(links.length).toBe(6);
    for (const a of links) {
      expect(a).toHaveAttribute("target", "_blank");
      expect(a.getAttribute("rel")).toContain("noopener");
      expect(a.getAttribute("rel")).toContain("noreferrer");
    }
  });

  it("is a plain card: no buttons, nothing that asks for money outside the one sentence", () => {
    render(<AboutCard />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("inside the desktop app asks the shell to open the page instead of leaving the app", () => {
    bridge.desktopMode = true;
    render(<AboutCard />);
    const notPrevented = fireEvent.click(screen.getByRole("link", { name: "Saweria" }));
    expect(notPrevented).toBe(false); // the click was cancelled, so the app is not replaced by the site
    expect(bridge.openExternal).toHaveBeenCalledWith(ABOUT.saweria);
  });
});

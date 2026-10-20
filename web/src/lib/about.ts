/** Who made Rekamind and where to find it. One place, so the About card, the page footer and the sign-in screen agree. */
export const ABOUT = {
  name: "Rochmad Handoko Aji",
  github: "https://github.com/handokoaji",
  instagram: "https://www.instagram.com/rhandokoaji/",
  repo: "https://github.com/handokoaji/rekamind",
  sponsors: "https://github.com/sponsors/handokoaji",
  saweria: "https://saweria.co/handokoaji",
} as const;

/** Taken from web/package.json at build time (scripts/set_version.py keeps that file in step with every release). */
export const APP_VERSION: string = __APP_VERSION__;

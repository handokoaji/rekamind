import { useEffect, useState } from "react";

/** "system" (the default) follows the operating system; the other two are the user's explicit choice. */
export type ThemeChoice = "system" | "light" | "dark";
const KEY = "rekamind.theme"; // public/theme-init.js reads the same key before the first paint

export function readTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

/** The stylesheet treats "no data-theme" as "follow the system", so that is what the default looks like in the DOM. */
export function applyTheme(choice: ThemeChoice): void {
  const el = document.documentElement;
  if (choice === "system") el.removeAttribute("data-theme");
  else el.setAttribute("data-theme", choice);
}

export function useTheme(): { choice: ThemeChoice; setChoice: (c: ThemeChoice) => void } {
  const [choice, setChoiceState] = useState<ThemeChoice>(readTheme);
  useEffect(() => applyTheme(choice), [choice]);
  const setChoice = (c: ThemeChoice) => {
    try {
      if (c === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, c);
    } catch { /* storage blocked: the choice lasts until the page is closed */ }
    setChoiceState(c);
  };
  return { choice, setChoice };
}

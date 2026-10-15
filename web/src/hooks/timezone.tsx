import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { getDisplayTimeZone, setDisplayTimeZone } from "../lib/format";
import { t } from "../lib/i18n";
import { useCapabilities } from "./queries";

/** "server" follows the server's zone (WIB unless the operator changed it); "device" the computer's own. */
export type ZoneChoice = "server" | "device" | string;
const KEY = "rekamind.tz";

export const zoneOptions = (): { value: ZoneChoice; label: string }[] => [
  { value: "server", label: t("Ikuti server") },
  { value: "Asia/Jakarta", label: "WIB (Jakarta)" },
  { value: "Asia/Makassar", label: "WITA (Makassar)" },
  { value: "Asia/Jayapura", label: "WIT (Jayapura)" },
  { value: "UTC", label: "UTC" },
  { value: "device", label: t("Zona perangkat ini") },
];

function readChoice(): ZoneChoice {
  try { return localStorage.getItem(KEY) || "server"; } catch { return "server"; }
}
const Ctx = createContext<{ choice: ZoneChoice; setChoice: (c: ZoneChoice) => void; effective: string | undefined }>({ choice: "server", setChoice: () => undefined, effective: undefined });
export const useTimeZoneChoice = () => useContext(Ctx);

/** Applies the zone before anything renders a time, and remounts the tree when it changes. */
export function TimeZoneProvider({ children }: { children: ReactNode }) {
  const caps = useCapabilities();
  const [choice, setChoiceState] = useState<ZoneChoice>(readChoice);
  const effective = choice === "device" ? undefined : choice === "server" ? (caps.data?.timezone ?? "Asia/Jakarta") : choice;
  setDisplayTimeZone(effective); // synchronous on purpose: children format times in this very render
  useEffect(() => { setDisplayTimeZone(effective); }, [effective]);
  const value = useMemo(() => ({
    choice, effective,
    setChoice: (c: ZoneChoice) => { try { localStorage.setItem(KEY, c); } catch { /* storage blocked: lasts for this visit */ } setChoiceState(c); },
  }), [choice, effective]);
  return <Ctx.Provider value={value}><div key={String(getDisplayTimeZone())} className="contents">{children}</div></Ctx.Provider>;
}

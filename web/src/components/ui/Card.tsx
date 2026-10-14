import type { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export function Card({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={cn("rounded-2xl border border-border bg-card shadow-[0_1px_2px_rgb(16_24_40/0.04)]", className)} />;
}

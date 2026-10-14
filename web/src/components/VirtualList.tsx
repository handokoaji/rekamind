import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

/** Renders only the rows near the viewport, for lists that can run to thousands (a multi-hour
 *  transcript, hundreds of tasks). Rows may differ in height and may change it (an inline editor
 *  opening): each is measured. Callers should switch to a plain list below a threshold so that
 *  find-in-page and screen readers see everything in ordinary cases. */
export function VirtualList<T>({ items, render, as: Tag = "ul", className, gap = 12, estimate = 100, label, itemClassName }: {
  items: T[]; render: (item: T, index: number) => ReactNode; as?: "ul" | "ol"; className?: string; gap?: number; estimate?: number;
  label?: string; itemClassName?: string;
}) {
  const ref = useRef<HTMLUListElement & HTMLOListElement>(null);
  const [margin, setMargin] = useState(0);
  useLayoutEffect(() => { setMargin(ref.current?.offsetTop ?? 0); }, []);
  const v = useWindowVirtualizer({ count: items.length, estimateSize: () => estimate, overscan: 8, scrollMargin: margin, gap });
  return (
    <Tag ref={ref} aria-label={label} className={className ? `relative ${className}` : "relative"} style={{ height: v.getTotalSize() }}>
      {v.getVirtualItems().map((it) => (
        <li key={it.key} data-index={it.index} ref={v.measureElement} aria-setsize={items.length} aria-posinset={it.index + 1}
          className={itemClassName ? `absolute left-0 top-0 w-full ${itemClassName}` : "absolute left-0 top-0 w-full"}
          style={{ transform: `translateY(${it.start - v.options.scrollMargin}px)` }}>
          {render(items[it.index]!, it.index)}
        </li>))}
    </Tag>
  );
}

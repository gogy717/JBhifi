import type { ReactNode } from "react";

import { Dot } from "@/components/ui";

const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 " +
  "focus-visible:ring-offset-canvas";

/** A short list of choices as pills, all in view at once (a status filter, a period, a state). One is always
 *  chosen; screen readers hear which through aria-pressed. */
export function FilterPills<T extends string | number | undefined>({ label, options, value, onChange }: {
  label: string;
  options: { value: T; label: ReactNode; count?: number }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((option) => {
        const chosen = option.value === value;
        return (
          <button key={String(option.value)} type="button" aria-pressed={chosen} onClick={() => onChange(option.value)}
            className={`inline-flex h-9 items-center gap-2 rounded-full px-4 text-sm font-semibold transition-colors
              ${focusRing} ${chosen ? "bg-ink text-white" : "border border-line bg-white text-ink hover:border-ink/40"}`}>
            {option.label}
            {option.count !== undefined && (
              <span className={`tabular-nums ${chosen ? "text-on-ink-muted" : "text-muted"}`}>{option.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export type CountTile = {
  key: string;
  label: string;
  /** undefined while loading. */
  count?: number;
  hint?: string;
  /** Work waiting on this store: shown in orange while there is any. */
  attention?: boolean;
};

/** How much is waiting at each step, so the work is visible before reading a row. Each tile is also a filter:
 *  choosing one shows just those rows, choosing it again goes back. */
export function CountTiles({ label, tiles, selected, onSelect }: {
  label: string;
  tiles: CountTile[];
  selected?: string;
  onSelect: (key: string) => void;
}) {
  return (
    <div role="group" aria-label={label} className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tiles.map((tile) => {
        const chosen = tile.key === selected;
        const waiting = tile.attention && (tile.count ?? 0) > 0;
        return (
          <button key={tile.key} type="button" aria-pressed={chosen} onClick={() => onSelect(tile.key)}
            className={`flex min-w-0 flex-col items-start gap-1 rounded-card border bg-white px-4 py-3.5 text-left
              transition-colors ${focusRing} ${chosen ? "border-ink ring-1 ring-ink" : "border-line hover:border-ink/30"}`}>
            <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-muted">
              {waiting && <Dot className="bg-warn" />}
              {tile.label}
            </span>
            <span className={`font-display text-3xl font-bold leading-tight tabular-nums
              ${waiting ? "text-warn-ink" : "text-ink"}`}>
              {tile.count ?? "–"}
            </span>
            {tile.hint && <span className="text-xs leading-snug text-muted">{tile.hint}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** The rule or requirement a part of the page demonstrates (BR09, R11, T2…), as a small tag for the demo. */
export function RuleTag({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full bg-sand px-2 py-0.5 font-mono text-[11px] font-semibold
      text-muted">
      {children}
    </span>
  );
}

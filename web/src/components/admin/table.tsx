import type { ReactNode, TdHTMLAttributes } from "react";

export type Column = string | { label: ReactNode; align?: "right" | "center"; srOnly?: boolean };

const ALIGN = { left: "text-left", right: "text-right", center: "text-center" } as const;

/** The admin's data table: a quiet header row of small capitals, rows about 52px high, and number columns
 *  right-aligned in tabular figures so they line up. On a phone it scrolls sideways inside its card, never the page. */
export function Table({ columns, label, loading = false, children }: {
  columns: Column[];
  /** What the table lists, for screen readers. */
  label: string;
  /** A newer list is loading: the old rows stay, dimmed. */
  loading?: boolean;
  children: ReactNode;
}) {
  return (
    // relative: screen-reader-only text in a cell is positioned absolutely, and without a containing block here it
    // would escape the scrolling box and widen the page.
    <div className={`relative overflow-x-auto transition-opacity ${loading ? "opacity-60" : ""}`}>
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{label}</caption>
        <thead>
          <tr className="border-b border-line">
            {columns.map((column, index) => {
              const { label: text, align, srOnly } = typeof column === "string" ? { label: column } : column;
              return (
                <th key={index} scope="col" className={`whitespace-nowrap px-4 py-3 text-xs font-semibold uppercase
                  tracking-[0.08em] text-muted first:pl-5 last:pr-5 ${ALIGN[align ?? "left"]}`}>
                  {srOnly ? <span className="sr-only">{text}</span> : text}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

export function Row({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <tr className={`transition-colors hover:bg-canvas ${className}`}>{children}</tr>;
}

/** A table cell. `numeric` right-aligns it in tabular figures; `align="center"` centres it. */
export function Cell({ numeric = false, align, className = "", children, ...props }: {
  numeric?: boolean;
  align?: "right" | "center";
  className?: string;
  children?: ReactNode;
} & TdHTMLAttributes<HTMLTableCellElement>) {
  const alignment = numeric ? "whitespace-nowrap text-right tabular-nums" : align ? ALIGN[align] : "";
  return (
    <td className={`px-4 py-3 align-middle first:pl-5 last:pr-5 ${alignment} ${className}`} {...props}>
      {children}
    </td>
  );
}

/** A product as the tables show it: the name, then brand, SKU and (optionally) category in small type. */
export function ProductName({ name, brand, sku, category, children }: {
  name: ReactNode;
  brand?: string;
  sku: string;
  category?: string;
  children?: ReactNode;
}) {
  return (
    <div className="min-w-48">
      <div className="font-semibold text-ink">{name}{children}</div>
      <div className="mt-0.5 text-xs text-muted">
        {brand && <>{brand} · </>}<span className="font-mono">{sku}</span>{category && <> · {category}</>}
      </div>
    </div>
  );
}

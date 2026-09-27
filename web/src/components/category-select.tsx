"use client";

import { selectClass } from "@/components/ui";
import type { Category } from "@/lib/api/client";

/** Categories grouped under their parent (the recursive category → parent relationship). */
export function CategorySelect({ categories, value, onChange, allLabel, leavesOnly = false }: {
  categories: Category[];
  value?: number;
  onChange: (id: number | undefined) => void;
  allLabel: string;
  leavesOnly?: boolean;
}) {
  const parents = categories.filter((c) => c.parent_id === null);
  return (
    <select className={selectClass} value={value ?? ""}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : undefined)}>
      <option value="">{allLabel}</option>
      {parents.map((parent) => {
        const children = categories.filter((c) => c.parent_id === parent.category_id);
        return leavesOnly ? (
          <optgroup key={parent.category_id} label={parent.name}>
            {children.map((c) => <option key={c.category_id} value={c.category_id}>{c.name}</option>)}
          </optgroup>
        ) : (
          [parent, ...children].map((c) => (
            <option key={c.category_id} value={c.category_id}>{c.parent_id ? `  — ${c.name}` : c.name}</option>
          ))
        );
      })}
    </select>
  );
}

import { selectClass } from "@/components/ui";
import type { Store } from "@/lib/api/client";

/** Pick a store, grouped by state. For support staff, who look at any store; store staff stay on their own. */
export function StoreSelect({ stores, value, onChange }: {
  stores: Store[];
  value: number;
  onChange: (id: number) => void;
}) {
  const states = [...new Set(stores.map((s) => s.state))];
  return (
    <select className={selectClass} value={value} onChange={(e) => onChange(Number(e.target.value))}>
      {states.map((state) => (
        <optgroup key={state} label={state}>
          {stores.filter((s) => s.state === state).map((s) => (
            <option key={s.store_id} value={s.store_id}>
              {s.name}{s.store_type === "warehouse" ? " (warehouse)" : ""}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

import { StoreIcon } from "@/components/admin/icons";
import { selectClass } from "@/components/ui";
import type { Store } from "@/lib/api/client";

/** Pick a store, grouped by state. For support staff, who look at any store; store staff stay on their own. */
export function StoreSelect({ stores, value, onChange, label = "Store" }: {
  stores: Store[];
  value: number;
  onChange: (id: number) => void;
  label?: string;
}) {
  const states = [...new Set(stores.map((s) => s.state))];
  return (
    <select aria-label={label} className={selectClass} value={value} onChange={(e) => onChange(Number(e.target.value))}>
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

/** Whose page this is: store staff see their own store as a fixed pill; support staff choose any store. */
export function StorePicker({ ownStore, stores, value, onChange }: {
  /** The store staff member's own store's name; undefined for support staff, who choose. */
  ownStore?: string;
  stores: Store[];
  value: number;
  onChange: (id: number) => void;
}) {
  if (ownStore !== undefined) {
    return (
      <span className="inline-flex h-11 items-center gap-2 rounded-full border border-line bg-white px-4 text-[15px]">
        <StoreIcon className="h-[18px] w-[18px] text-brand-strong" />
        <span className="text-muted">Store</span>
        <strong className="font-semibold">{ownStore}</strong>
      </span>
    );
  }
  return (
    <span className="flex w-full items-center gap-2 sm:w-72">
      <StoreIcon className="h-[18px] w-[18px] text-brand-strong" />
      <StoreSelect stores={stores} value={value} onChange={onChange} />
    </span>
  );
}

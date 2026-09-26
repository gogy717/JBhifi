"use client";

import { useDeferredValue, useState } from "react";

import { useAdminSession } from "@/components/admin/session";
import { CategorySelect } from "@/components/category-select";
import {
  Badge, Button, Card, Empty, ErrorBox, Field, inputClass, LOW_STOCK, Modal, NoticeBanner, PageHeader,
  selectClass, StockBadge, useNotice,
} from "@/components/ui";
import {
  type Adjustment, type AdjustmentReason, type ApiError, api, call, type InventoryRow, type Store, toApiError,
} from "@/lib/api/client";
import { money, signed, timeAgo } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

const REASONS: Record<AdjustmentReason, string> = {
  received: "Received delivery",
  damaged: "Damaged or lost",
  stocktake: "Stocktake count",
};
// BR18: received stock is added, damaged stock removed, a stocktake can go either way.
const REASONS_FOR = { add: ["received", "stocktake"], remove: ["damaged", "stocktake"] } as const;

export default function InventoryPage() {
  const [storeId, setStoreId] = useState(1);
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search.trim());
  const [categoryId, setCategoryId] = useState<number>();
  const [lowOnly, setLowOnly] = useState(false);
  const [quickReason, setQuickReason] = useState<AdjustmentReason>("stocktake");
  const [dialog, setDialog] = useState<{ row: InventoryRow; direction: "add" | "remove" }>();
  const [busyId, setBusyId] = useState<number>();
  const { notice, showError, showSuccess, clear } = useNotice();
  const { session, signedIn } = useAdminSession();

  const stores = useLoad("stores", () => call(api.GET("/api/v1/stores")));
  const categories = useLoad("categories", () => call(api.GET("/api/v1/categories")));
  const inventoryKey = `inventory:${storeId}:${q}:${categoryId}:${lowOnly}`;
  const inventory = useLoad(inventoryKey, () =>
    call(api.GET("/api/v1/stores/{store_id}/inventory", {
      params: {
        path: { store_id: storeId },
        query: { q: q || undefined, category_id: categoryId, low_stock_only: lowOnly, low_stock_threshold: LOW_STOCK },
      },
    })));
  // The history is staff-only, so it is only requested once a staff session exists.
  const historyKey = `adjustments:${storeId}:${signedIn ? "staff" : "guest"}`;
  const history = useLoad(historyKey, () =>
    !signedIn
      ? Promise.resolve([])
      : call(api.GET("/api/v1/stores/{store_id}/adjustments", {
        params: { path: { store_id: storeId }, query: { limit: 30 } },
      })));

  const store = stores.data?.find((s) => s.store_id === storeId);
  // The server decides this too; the UI only explains it in advance.
  const canAdjust = signedIn && session?.staff_type === "store" && session.store_id === storeId;
  const rows = inventory.data ?? [];

  function changeStore(id: number) {
    setStoreId(id);
    clear();
  }

  /** One API call = one transaction: stock change + log row, or nothing (see app/services/inventory.py). */
  async function adjust(row: InventoryRow, delta: number, reason: AdjustmentReason, note?: string) {
    if (!canAdjust) return undefined;
    setBusyId(row.product_id);
    try {
      const result = await call(api.POST("/api/v1/stores/{store_id}/inventory/{product_id}/adjustments", {
        params: { path: { store_id: storeId, product_id: row.product_id } },
        body: { delta, reason, note: note || null },     // who: the session, never this body
      }));
      inventory.setData(inventoryKey, (list) =>
        list.map((r) => (r.product_id === row.product_id ? { ...r, quantity: result.quantity_after } : r)));
      history.setData(historyKey, (list) => [result, ...list].slice(0, 30));
      showSuccess(<>
        <b>{row.name}</b> at {store?.name}: {row.quantity} → <b>{result.quantity_after}</b>
        {" "}({signed(delta)}, {REASONS[reason].toLowerCase()}, by {result.staff_name})
      </>);
      return undefined;
    } catch (error) {
      return toApiError(error);
    } finally {
      setBusyId(undefined);
    }
  }

  async function quickAdjust(row: InventoryRow, delta: 1 | -1) {
    const error = await adjust(row, delta, quickReason);
    if (error) showError(error);
  }

  const outOfStock = rows.filter((r) => r.quantity === 0).length;
  const low = rows.filter((r) => r.quantity > 0 && r.quantity <= LOW_STOCK).length;

  return (
    <>
      <title>Inventory · JB Admin</title>
      <PageHeader
        title="Inventory"
        description={<>
          Stock at each location. Every change is one transaction that updates the quantity and writes an
          audit row saying who, why and by how much (BR18). The database refuses stock below zero (BR03).
        </>}
      />

      <Card className="mb-4">
        <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-[repeat(2,minmax(0,1.25fr))_repeat(3,minmax(0,1fr))]">
          <Field label="Store">
            <StoreSelect stores={stores.data ?? []} value={storeId} onChange={changeStore} />
          </Field>
          <Field label="Acting as"
            hint={canAdjust
              ? "Who the log records — the session's staff member, never this page's request body."
              : <span className="text-amber-700">
                Sign in above as staff who work at this store. The database refuses anyone else (BR18).
              </span>}>
            <input className={inputClass} readOnly value={canAdjust ? session?.display_name ?? "" : "Not signed in"} />
          </Field>
          <Field label="Search">
            <input className={inputClass} placeholder="Name, SKU or brand" value={search}
              onChange={(e) => setSearch(e.target.value)} />
          </Field>
          <Field label="Category">
            <CategorySelect categories={categories.data ?? []} value={categoryId} onChange={setCategoryId}
              allLabel="All categories" />
          </Field>
          <Field label="Reason for ± buttons">
            <select className={selectClass} value={quickReason}
              onChange={(e) => setQuickReason(e.target.value as AdjustmentReason)}>
              {Object.entries(REASONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </Field>
        </div>
      </Card>

      <NoticeBanner notice={notice} onClose={clear} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Card
          title={<>
            {store ? `${store.name}` : "Stock"}
            {store?.store_type === "warehouse" && <span className="ml-2"><Badge tone="blue">warehouse</Badge></span>}
            <span className="ml-3 font-normal text-neutral-500">
              {rows.length} products · <span className="text-red-600">{outOfStock} out of stock</span> ·{" "}
              <span className="text-amber-700">{low} low (≤ {LOW_STOCK})</span>
            </span>
          </>}
          actions={
            <label className="flex items-center gap-2 text-sm text-neutral-700">
              <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)}
                className="h-4 w-4 accent-neutral-900" />
              Low stock only
            </label>
          }
        >
          {inventory.error && <ErrorBox error={inventory.error} className="m-4" />}
          {!inventory.error && rows.length === 0 && (
            <Empty>{inventory.loading ? "Loading…" : "No products match."}</Empty>
          )}
          {rows.length > 0 && (
            <div className={`overflow-x-auto ${inventory.loading ? "opacity-60" : ""}`}>
              <table className="w-full text-sm">
                <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500">
                  <tr>
                    <th className="px-4 py-2 font-medium">Product</th>
                    <th className="px-4 py-2 font-medium">Category</th>
                    <th className="px-4 py-2 text-right font-medium">Price</th>
                    <th className="whitespace-nowrap px-4 py-2 text-center font-medium">On hand</th>
                    <th className="px-4 py-2 text-right font-medium">Adjust</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100">
                  {rows.map((row) => (
                    <tr key={row.product_id} className="hover:bg-neutral-50">
                      <td className="px-4 py-2.5">
                        <div className="font-medium text-neutral-900">
                          {row.name} {!row.is_active && <Badge>retired</Badge>}
                        </div>
                        <div className="text-xs text-neutral-500">
                          {row.brand} · <span className="font-mono">{row.sku}</span>
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-neutral-600">{row.category}</td>
                      <td className="whitespace-nowrap px-4 py-2.5 text-right tabular-nums">
                        {row.on_sale && <span className="mr-1.5"><Badge tone="sale">sale</Badge></span>}
                        {money(row.current_price)}
                      </td>
                      <td className="px-4 py-2.5 text-center"><StockBadge quantity={row.quantity} /></td>
                      <td className="px-4 py-2.5">
                        <div className="flex justify-end gap-1">
                          <Button size="sm" aria-label={`Remove one ${row.name}`}
                            disabled={!canAdjust || busyId === row.product_id}
                            onClick={() => quickAdjust(row, -1)}>−1</Button>
                          <Button size="sm" aria-label={`Add one ${row.name}`}
                            disabled={!canAdjust || busyId === row.product_id}
                            onClick={() => quickAdjust(row, 1)}>+1</Button>
                          <Button size="sm" tone="ghost" disabled={!canAdjust}
                            onClick={() => setDialog({ row, direction: "add" })}>
                            Adjust…
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title="Recent adjustments" actions={<span className="text-xs text-neutral-500">{store?.name}</span>}>
          <AdjustmentList adjustments={history.data ?? []} loading={history.loading} error={history.error} />
        </Card>
      </div>

      {dialog && (
        <AdjustDialog
          row={dialog.row}
          initialDirection={dialog.direction}
          storeName={store?.name ?? ""}
          actorName={session?.display_name ?? "nobody"}
          onClose={() => setDialog(undefined)}
          onSubmit={async (delta, reason, note) => {
            const error = await adjust(dialog.row, delta, reason, note);
            if (!error) setDialog(undefined);
            return error;
          }}
        />
      )}
    </>
  );
}

function StoreSelect({ stores, value, onChange }: {
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

function AdjustmentList({ adjustments, loading, error }: {
  adjustments: Adjustment[];
  loading: boolean;
  error?: ApiError;
}) {
  if (error) return <ErrorBox error={error} className="m-4" />;
  if (adjustments.length === 0) {
    return <Empty>{loading ? "Loading…" : "No adjustments at this store yet. Try the ± buttons."}</Empty>;
  }
  return (
    <ol className="divide-y divide-neutral-100">
      {adjustments.map((a) => (
        <li key={a.adjustment_id} className="px-4 py-3 text-sm">
          <div className="flex items-baseline justify-between gap-2">
            <span className={`font-semibold tabular-nums ${a.delta > 0 ? "text-emerald-700" : "text-red-700"}`}>
              {signed(a.delta)}
            </span>
            <span className="text-xs text-neutral-500">{REASONS[a.reason]}</span>
            <span className="ml-auto text-xs tabular-nums text-neutral-500">now {a.quantity_after}</span>
          </div>
          <div className="truncate text-neutral-900">{a.product_name}</div>
          <div className="text-xs text-neutral-500">
            {a.staff_name} · {timeAgo(a.adjusted_at)}{a.note && <> · “{a.note}”</>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function AdjustDialog({ row, initialDirection, storeName, actorName, onClose, onSubmit }: {
  row: InventoryRow;
  initialDirection: "add" | "remove";
  storeName: string;
  actorName: string;
  onClose: () => void;
  onSubmit: (delta: number, reason: AdjustmentReason, note: string) => Promise<ApiError | undefined>;
}) {
  const [direction, setDirection] = useState(initialDirection);
  const [amount, setAmount] = useState("1");
  const [reason, setReason] = useState<AdjustmentReason>(REASONS_FOR[initialDirection][0]);
  const [note, setNote] = useState("");
  const [error, setError] = useState<ApiError>();
  const [saving, setSaving] = useState(false);

  const units = Number(amount);
  const valid = Number.isInteger(units) && units > 0;
  const delta = direction === "add" ? units : -units;
  const after = row.quantity + delta;

  function changeDirection(next: "add" | "remove") {
    setDirection(next);
    setReason(REASONS_FOR[next][0]);
  }

  async function save() {
    setSaving(true);
    setError(await onSubmit(delta, reason, note.trim()));
    setSaving(false);
  }

  return (
    <Modal
      title={<>Adjust stock · <span className="font-normal text-neutral-600">{storeName}</span></>}
      onClose={onClose}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button tone="primary" disabled={!valid || saving} onClick={save}>
          {saving ? "Saving…" : "Save adjustment"}
        </Button>
      </>}
    >
      <div>
        <div className="font-medium">{row.name}</div>
        <div className="text-xs text-neutral-500">{row.brand} · <span className="font-mono">{row.sku}</span></div>
      </div>

      <div className="grid grid-cols-2 gap-1 rounded-lg bg-neutral-100 p-1">
        {(["add", "remove"] as const).map((d) => (
          <button key={d} type="button" onClick={() => changeDirection(d)}
            className={`rounded-md py-1.5 text-sm font-medium ${
              direction === d ? "bg-white shadow-sm" : "text-neutral-600 hover:text-neutral-900"}`}>
            {d === "add" ? "Add stock" : "Remove stock"}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Units">
          <input className={inputClass} type="number" min={1} step={1} value={amount} autoFocus
            onChange={(e) => setAmount(e.target.value)} />
        </Field>
        <Field label="Reason">
          <select className={selectClass} value={reason} onChange={(e) => setReason(e.target.value as AdjustmentReason)}>
            {REASONS_FOR[direction].map((r) => <option key={r} value={r}>{REASONS[r]}</option>)}
          </select>
        </Field>
      </div>

      <Field label="Note (optional)">
        <input className={inputClass} placeholder="e.g. delivery docket #, what was damaged" value={note}
          maxLength={500} onChange={(e) => setNote(e.target.value)} />
      </Field>

      <div className="flex items-center justify-between rounded-lg border border-neutral-200 px-4 py-3">
        <div className="text-sm text-neutral-600">On hand</div>
        <div className="flex items-center gap-2 text-lg font-semibold tabular-nums">
          {row.quantity} <span className="text-neutral-400">→</span>
          <span className={after < 0 ? "text-red-600" : ""}>{valid ? after : "?"}</span>
        </div>
      </div>
      {valid && after < 0 && (
        <p className="text-xs text-red-700">
          Below zero — the database will refuse this (BR03). Save anyway to see it happen.
        </p>
      )}
      <p className="text-xs text-neutral-500">Logged as {actorName} — from the signed-in session.</p>

      {error && <ErrorBox error={error} />}
    </Modal>
  );
}

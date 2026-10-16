"use client";

import { useDeferredValue, useState } from "react";

import { RuleTag } from "@/components/admin/filters";
import { SearchIcon } from "@/components/admin/icons";
import { useStaff } from "@/components/admin/staff-gate";
import { StorePicker } from "@/components/admin/store-select";
import { Cell, ProductName, Row, Table } from "@/components/admin/table";
import { CategorySelect } from "@/components/category-select";
import {
  Badge, Button, Card, Dot, Empty, ErrorBox, Field, inputClass, LOW_STOCK, Modal, NoticeBanner, PageHeader,
  selectClass, StockBadge, useNotice,
} from "@/components/ui";
import {
  type Adjustment, type AdjustmentReason, type ApiError, api, call, type InventoryRow, toApiError,
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
  const me = useStaff();
  // Store staff adjust their own store's stock; support staff look at any store but don't adjust (spec §4.5).
  const canAdjust = me.staff_type === "store";
  const [storeId, setStoreId] = useState(me.store_id ?? 1);
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search.trim());
  const [categoryId, setCategoryId] = useState<number>();
  const [lowOnly, setLowOnly] = useState(false);
  const [quickReason, setQuickReason] = useState<AdjustmentReason>("stocktake");
  const [dialog, setDialog] = useState<{ row: InventoryRow; direction: "add" | "remove" }>();
  const [busyId, setBusyId] = useState<number>();
  const { notice, showError, showSuccess, clear } = useNotice();

  const stores = useLoad("stores", () => call(api.GET("/api/v1/stores")));
  const categories = useLoad("categories", () => call(api.GET("/api/v1/categories")));
  const inventory = useLoad(`inventory:${storeId}:${q}:${categoryId}:${lowOnly}`, () =>
    call(api.GET("/api/v1/stores/{store_id}/inventory", {
      params: {
        path: { store_id: storeId },
        query: { q: q || undefined, category_id: categoryId, low_stock_only: lowOnly, low_stock_threshold: LOW_STOCK },
      },
    })));
  const history = useLoad(`adjustments:${storeId}`, () =>
    call(api.GET("/api/v1/stores/{store_id}/adjustments", {
      params: { path: { store_id: storeId }, query: { limit: 30 } },
    })));

  const store = stores.data?.find((s) => s.store_id === storeId);
  const rows = inventory.data ?? [];

  function changeStore(id: number) {
    setStoreId(id);
    clear();
  }

  /** One API call = one transaction: stock change + log row, or nothing (see app/services/inventory.py). */
  async function adjust(row: InventoryRow, delta: number, reason: AdjustmentReason, note?: string) {
    setBusyId(row.product_id);
    try {
      const result = await call(api.POST("/api/v1/stores/{store_id}/inventory/{product_id}/adjustments", {
        params: { path: { store_id: storeId, product_id: row.product_id } },
        body: { delta, reason, note: note || null },
      }));
      inventory.setData((list) =>
        list.map((r) => (r.product_id === row.product_id ? { ...r, quantity: result.quantity_after } : r)));
      history.setData((list) => [result, ...list].slice(0, 30));
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
      <title>Inventory · TechLight Admin</title>
      <PageHeader
        title="Inventory"
        description={<>
          Stock at each location. Every change is one transaction that updates the quantity and writes an
          audit row saying who, why and by how much (BR18). The database refuses stock below zero (BR03).
        </>}
        actions={<StorePicker ownStore={canAdjust ? store?.name ?? "…" : undefined} stores={stores.data ?? []}
          value={storeId} onChange={changeStore} />}
      />

      <Card className="mb-5">
        <div className="grid grid-cols-1 gap-4 p-5 sm:grid-cols-2 xl:grid-cols-[minmax(0,2fr)_repeat(2,minmax(0,1fr))]">
          <Field label="Search">
            <span className="relative block">
              <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
              <input className={`${inputClass} pl-10`} placeholder="Name, SKU or brand" value={search}
                onChange={(e) => setSearch(e.target.value)} />
            </span>
          </Field>
          <Field label="Category">
            <CategorySelect categories={categories.data ?? []} value={categoryId} onChange={setCategoryId}
              allLabel="All categories" />
          </Field>
          <Field label="Reason for ± buttons">
            <select className={selectClass} value={quickReason} disabled={!canAdjust}
              onChange={(e) => setQuickReason(e.target.value as AdjustmentReason)}>
              {Object.entries(REASONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </Field>
        </div>
        <p className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3 text-sm text-muted">
          Signed in as <b className="font-semibold text-ink">{me.display_name}</b> ·{" "}
          {canAdjust ? "every change is logged under your name." : "support staff can look at any store's stock but don't adjust it."}
          <RuleTag>BR18</RuleTag>
        </p>
      </Card>

      <NoticeBanner notice={notice} onClose={clear} />

      <div className="grid grid-cols-1 gap-5 2xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Card className="self-start">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
              <h2 className="text-base font-bold">{store?.name ?? "Stock"}</h2>
              {store?.store_type === "warehouse" && <Badge tone="blue">warehouse</Badge>}
              <span className="text-muted"><span className="tabular-nums">{rows.length}</span> products</span>
              <span className="flex items-center gap-1.5 font-semibold text-ink">
                <Dot className="bg-muted" />
                <span className="tabular-nums">{outOfStock}</span> out of stock
              </span>
              <span className="flex items-center gap-1.5 font-semibold text-warn-ink">
                <Dot className="bg-warn" />
                <span className="tabular-nums">{low}</span> low (≤ {LOW_STOCK})
              </span>
            </div>
            <label className="flex cursor-pointer items-center gap-2 rounded-full border border-line px-3.5 py-1.5
              text-sm font-semibold has-checked:border-ink has-checked:bg-ink has-checked:text-white">
              <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)}
                className="h-4 w-4 accent-brand-strong" />
              Low stock only
            </label>
          </div>
          {inventory.error && <ErrorBox error={inventory.error} className="m-5" />}
          {!inventory.error && rows.length === 0 && (
            <Empty>{inventory.loading ? "Loading…" : "No products match."}</Empty>
          )}
          {rows.length > 0 && (
            <Table label={`Stock at ${store?.name ?? "this store"}`} loading={inventory.loading}
              columns={["Product", { label: "Price", align: "right" }, { label: "On hand", align: "center" },
                ...(canAdjust ? [{ label: "Adjust", align: "right" } as const] : [])]}>
              {rows.map((row) => (
                <Row key={row.product_id}>
                  <Cell>
                    <ProductName name={row.name} brand={row.brand} sku={row.sku} category={row.category}>
                      {!row.is_active && <span className="ml-2"><Badge>retired</Badge></span>}
                    </ProductName>
                  </Cell>
                  <Cell numeric>
                    {row.on_sale && <span className="mr-1.5"><Badge tone="sale">sale</Badge></span>}
                    {money(row.current_price)}
                  </Cell>
                  <Cell align="center"><StockBadge quantity={row.quantity} /></Cell>
                  {canAdjust && (
                    <Cell>
                      <div className="flex justify-end gap-1.5">
                        <Button size="sm" aria-label={`Remove one ${row.name}`}
                          disabled={busyId === row.product_id} onClick={() => quickAdjust(row, -1)}>−1</Button>
                        <Button size="sm" aria-label={`Add one ${row.name}`}
                          disabled={busyId === row.product_id} onClick={() => quickAdjust(row, 1)}>+1</Button>
                        <Button size="sm" tone="ghost" onClick={() => setDialog({ row, direction: "add" })}>
                          Adjust…
                        </Button>
                      </div>
                    </Cell>
                  )}
                </Row>
              ))}
            </Table>
          )}
        </Card>

        <Card className="self-start" title="Recent adjustments" actions={<span className="text-xs text-muted">{store?.name}</span>}>
          <AdjustmentList adjustments={history.data ?? []} loading={history.loading} error={history.error} />
        </Card>
      </div>

      {dialog && (
        <AdjustDialog
          row={dialog.row}
          initialDirection={dialog.direction}
          storeName={store?.name ?? ""}
          actorName={me.display_name}
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

function AdjustmentList({ adjustments, loading, error }: {
  adjustments: Adjustment[];
  loading: boolean;
  error?: ApiError;
}) {
  if (error) return <ErrorBox error={error} className="m-5" />;
  if (adjustments.length === 0) {
    return <Empty>{loading ? "Loading…" : "No adjustments at this store yet. Try the ± buttons."}</Empty>;
  }
  return (
    <ol className="divide-y divide-line">
      {adjustments.map((a) => (
        <li key={a.adjustment_id} className="flex gap-3 px-5 py-3 text-sm">
          <span className={`mt-0.5 inline-flex h-7 min-w-11 shrink-0 items-center justify-center rounded-full px-2
            text-xs font-bold tabular-nums ${a.delta > 0 ? "bg-emerald-50 text-ok" : "bg-red-50 text-red-700"}`}>
            {signed(a.delta)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate font-semibold text-ink">{a.product_name}</span>
              <span className="shrink-0 text-xs tabular-nums text-muted">now {a.quantity_after}</span>
            </div>
            <div className="text-xs text-muted">
              {REASONS[a.reason]} · {a.staff_name} · {timeAgo(a.adjusted_at)}
            </div>
            {a.note && <div className="mt-0.5 truncate text-xs text-muted">“{a.note}”</div>}
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
      title={<>Adjust stock · <span className="font-sans font-normal text-muted">{storeName}</span></>}
      onClose={onClose}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button tone="primary" disabled={!valid || saving} onClick={save}>
          {saving ? "Saving…" : "Save adjustment"}
        </Button>
      </>}
    >
      <ProductName name={row.name} brand={row.brand} sku={row.sku} />

      <div role="group" aria-label="Direction" className="grid grid-cols-2 gap-1 rounded-full bg-sand p-1">
        {(["add", "remove"] as const).map((d) => (
          <button key={d} type="button" aria-pressed={direction === d} onClick={() => changeDirection(d)}
            className={`h-9 rounded-full text-sm font-semibold transition-colors focus-visible:outline-hidden
              focus-visible:ring-2 focus-visible:ring-brand ${
              direction === d ? "bg-white text-ink shadow-sm" : "text-muted hover:text-ink"}`}>
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

      <div className="flex items-center justify-between rounded-tile bg-canvas px-4 py-3">
        <div className="text-sm text-muted">On hand</div>
        <div className="flex items-center gap-2 font-display text-2xl font-bold tabular-nums">
          {row.quantity} <span className="text-faint">→</span>
          <span className={after < 0 ? "text-red-600" : ""}>{valid ? after : "?"}</span>
        </div>
      </div>
      {valid && after < 0 && (
        <p className="text-xs text-red-700">
          Below zero — the database will refuse this (BR03). Save anyway to see it happen.
        </p>
      )}
      <p className="text-xs text-muted">Logged as {actorName}.</p>

      {error && <ErrorBox error={error} />}
    </Modal>
  );
}

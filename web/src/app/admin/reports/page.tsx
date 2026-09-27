"use client";

import { useState } from "react";

import { useAdminSession } from "@/components/admin/session";
import { Button, Card, Empty, ErrorBox, Field, inputClass, PageHeader, selectClass, StockBadge } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { formatDate, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

function isoDay(offsetDays: number): string {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

export default function ReportsPage() {
  const { session, signedIn } = useAdminSession();
  const [chosenStore, setChosenStore] = useState<number>();
  const [from, setFrom] = useState(isoDay(-29));
  const [to, setTo] = useState(isoDay(1));
  const stores = useLoad("stores", () => call(api.GET("/api/v1/stores")));

  const retailStores = (stores.data ?? []).filter((row) => row.store_type === "retail");
  const storeId = chosenStore ?? session?.store_id ?? retailStores[0]?.store_id;
  const isSupport = session?.staff_type === "support";
  const window = { from_date: from, to_date: to, store_id: storeId };

  const sales = useLoad(`report-sales:${storeId}:${from}:${to}:${signedIn}`, () =>
    !signedIn || storeId === undefined
      ? Promise.resolve(undefined)
      : call(api.GET("/api/v1/reports/sales", { params: { query: window } })));
  const lowStock = useLoad(`report-low:${storeId}:${signedIn}`, () =>
    !signedIn || storeId === undefined
      ? Promise.resolve(undefined)
      : call(api.GET("/api/v1/reports/low-stock", { params: { query: { store_id: storeId, threshold: 3 } } })));
  const returns = useLoad(`report-returns:${storeId}:${from}:${to}:${signedIn}`, () =>
    !signedIn || storeId === undefined
      ? Promise.resolve(undefined)
      : call(api.GET("/api/v1/reports/returns", { params: { query: window } })));

  const salesRow = sales.data?.rows[0];
  const returnsRow = returns.data?.rows[0];
  const error = sales.error ?? lowStock.error ?? returns.error;

  return (
    <>
      <title>Reports · JB Admin</title>
      <PageHeader title="Reports" description={<>
        Money is counted by each payment&apos;s own event time; returns are the cohort of requests created in
        the period, whatever has happened to them since. Dates are Sydney calendar dates, the first
        inclusive and the second exclusive.
      </>} />

      <Card className="mb-4">
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Store">
            <select className={selectClass} value={storeId ?? ""} aria-label="Store"
              onChange={(event) => setChosenStore(Number(event.target.value))}>
              {(stores.data ?? []).map((row) => (
                <option key={row.store_id} value={row.store_id}>
                  {row.name}{row.store_type === "warehouse" ? " (warehouse)" : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="From (inclusive)" hint="Sydney">
            <input className={inputClass} type="date" value={from} aria-label="From date"
              onChange={(event) => setFrom(event.target.value)} />
          </Field>
          <Field label="To (exclusive)" hint="Sydney">
            <input className={inputClass} type="date" value={to} aria-label="To date"
              onChange={(event) => setTo(event.target.value)} />
          </Field>
          <div className="flex items-end">
            <Button onClick={() => { sales.reload(); lowStock.reload(); returns.reload(); }}>Refresh</Button>
          </div>
        </div>
      </Card>

      {!signedIn && (
        <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Sign in above as staff to see reports.
        </p>
      )}
      {signedIn && !isSupport && session?.store_id !== storeId && (
        <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          You are signed in for another store; the API will refuse these figures.
        </p>
      )}
      {error && <ErrorBox error={error} className="mb-4" />}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="Sales and refunds" actions={
          <span className="text-xs text-neutral-500">
            {sales.data?.window ? `${formatDate(sales.data.window.from_at)} → ${formatDate(sales.data.window.to_at)}` : ""}
          </span>}
        >
          {sales.loading && !sales.data && <Empty>Loading…</Empty>}
          {sales.data && !salesRow && <Empty>No trade in this period for that store.</Empty>}
          {salesRow && (
            <div className="divide-y divide-neutral-100">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 px-4 py-4 text-sm sm:grid-cols-3">
                <Figure label="Captured" amount={salesRow.captured_amount} />
                <Figure label="Refunded" amount={salesRow.refunded_amount} />
                <Figure label="Net receipts" amount={salesRow.net_receipts} emphasis />
                <Figure label="Orders placed" text={String(salesRow.order_count)} />
                <Figure label="Orders charged" text={String(salesRow.charged_orders)} />
                <Figure label="Refunds" text={String(salesRow.refund_count)} />
              </dl>
              <p className="px-4 py-3 text-xs text-neutral-500">
                A charge is counted on the day the payment was recorded, not the day the order was placed, so
                an order placed last month and charged today shows up today.
              </p>
            </div>
          )}
        </Card>

        <Card title="Returns desk activity" actions={<span className="text-xs text-neutral-500">cohort</span>}>
          {returns.loading && !returns.data && <Empty>Loading…</Empty>}
          {returns.data && !returnsRow && <Empty>No returns were requested in this period.</Empty>}
          {returnsRow && (
            <div className="divide-y divide-neutral-100">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 px-4 py-4 text-sm sm:grid-cols-3">
                <Figure label="Requested" text={String(returnsRow.requested_count)} />
                <Figure label="Received" text={String(returnsRow.received_count)} />
                <Figure label="Refunded" text={String(returnsRow.refunded_count)} />
                <Figure label="Rejected" text={String(returnsRow.rejected_count)} />
                <Figure label="Refunded value" amount={returnsRow.refunded_amount} emphasis />
              </dl>
              <p className="px-4 py-3 text-xs text-neutral-500">
                Attributed to the store that fulfilled the order. Items were received at{" "}
                {returnsRow.receiving_stores ?? "no store yet"}.
              </p>
            </div>
          )}
        </Card>
      </div>

      <Card className="mt-4" title="Low stock"
        actions={<span className="text-xs text-neutral-500">
          active products at or below 3{lowStock.data ? ` at ${lowStock.data.store_name}` : ""}
        </span>}>
        {lowStock.loading && !lowStock.data && <Empty>Loading…</Empty>}
        {lowStock.data && lowStock.data.rows.length === 0 && (
          <Empty>Nothing is low at this store right now.</Empty>
        )}
        {lowStock.data && lowStock.data.rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Product</th>
                  <th className="px-4 py-2 font-medium">Category</th>
                  <th className="px-4 py-2 text-right font-medium">Price</th>
                  <th className="px-4 py-2 text-center font-medium">On hand</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {lowStock.data.rows.map((row) => (
                  <tr key={row.product_id} className="hover:bg-neutral-50">
                    <td className="px-4 py-2.5">
                      <div className="font-medium">{row.name}</div>
                      <div className="text-xs text-neutral-500">
                        {row.brand} · <span className="font-mono">{row.sku}</span>
                        {!row.has_inventory_row && " · never stocked here"}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-neutral-600">{row.category}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{money(row.current_price)}</td>
                    <td className="px-4 py-2.5 text-center"><StockBadge quantity={row.quantity} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

function Figure({ label, amount, text, emphasis = false }: {
  label: string; amount?: string; text?: string; emphasis?: boolean;
}) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-neutral-500">{label}</dt>
      <dd className={`tabular-nums ${emphasis ? "text-lg font-bold" : "font-semibold"}`}>
        {amount !== undefined ? money(amount) : text}
      </dd>
    </div>
  );
}

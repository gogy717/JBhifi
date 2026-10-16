"use client";

import { type ReactNode, useState } from "react";

import { useStaff } from "@/components/admin/staff-gate";
import { StoreSelect } from "@/components/admin/store-select";
import { Button, Card, Empty, ErrorBox, Field, PageHeader, selectClass, StockBadge } from "@/components/ui";
import { api, call, type StockedEverywhere, type StoreReport } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

const WINDOWS = [7, 30, 90] as const;
const STATES = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"] as const;

/** A rate from the API ("0.2500") as a percentage; null (nothing sold) as a dash. */
function percent(rate: string | null): string {
  return rate === null ? "—" : `${(Number(rate) * 100).toFixed(1)}%`;
}

export default function ReportsPage() {
  const me = useStaff();
  const isSupport = me.staff_type === "support";
  // R9: a store's manager reads its report; support reads any store's. The API decides — this only picks
  // what to show first.
  const canRead = isSupport || me.runs_store;
  const [storeId, setStoreId] = useState(me.store_id ?? 1);
  const [days, setDays] = useState<number>(30);

  const stores = useLoad("stores", () => call(api.GET("/api/v1/stores")));
  const report = useLoad(`report:${storeId}:${days}:${canRead}`, () => canRead
    ? call(api.GET("/api/v1/stores/{store_id}/report", { params: { path: { store_id: storeId }, query: { days } } }))
    : Promise.resolve(undefined));
  const data = report.data;

  return (
    <>
      <title>Reports · TechLight Admin</title>
      <PageHeader
        title="Reports"
        description={<>
          A store&apos;s low stock, sales by category and return rate (R9). Every section is read from one
          snapshot of the database (<code>REPEATABLE READ</code>), so the figures always agree with each other.
        </>}
      />

      {canRead ? (
        <>
          <Card className="mb-4">
            <div className="grid gap-3 p-4 sm:grid-cols-2">
              <Field label="Store">
                {isSupport
                  ? <StoreSelect stores={stores.data ?? []} value={storeId} onChange={setStoreId} />
                  : <p className="flex h-9 items-center text-sm font-medium">{me.store_name}</p>}
              </Field>
              <Field label="Sales in the last" hint="Low stock always uses the last 30 days' sales rate.">
                <div className="flex gap-1">
                  {WINDOWS.map((n) => (
                    <Button key={n} tone={n === days ? "primary" : "secondary"} onClick={() => setDays(n)}>
                      {n} days
                    </Button>
                  ))}
                </div>
              </Field>
            </div>
          </Card>

          {report.error && <ErrorBox error={report.error} className="mb-4" />}
          {!data && !report.error && <Empty>Loading…</Empty>}
          {data && <ReportSections report={data} loading={report.loading} />}
        </>
      ) : (
        <Card className="mb-4">
          <p className="p-4 text-sm text-neutral-600">
            Store reports are for the store&apos;s manager and for support staff.
          </p>
        </Card>
      )}

      <StockedEverywherePanel />
    </>
  );
}

function ReportSections({ report, loading }: { report: StoreReport; loading: boolean }) {
  const total = report.sales_total;
  return (
    <div className={`space-y-4 ${loading ? "opacity-60" : ""}`}>
      <p className="text-xs text-neutral-500">
        {report.store_name} · sales placed in the {report.days} days to {formatDateTime(report.generated_at)}
      </p>

      <div className="grid gap-4 sm:grid-cols-3">
        <Tile label="Revenue" value={money(total.revenue)} />
        <Tile label="Orders" value={String(total.orders)} />
        <Tile label="Units sold" value={String(total.units)} />
      </div>

      <Card title={<>Low stock <span className="font-normal text-neutral-500">
        · 3 or fewer left, or under 14 days at the last 30 days&apos; rate</span></>}>
        {report.low_stock.length === 0 ? <Empty>Nothing is running low.</Empty> : (
          <Table head={["Product", "Category", "On hand", "Sold (30 days)", "Days of cover"]} left={2}>
            {report.low_stock.map((row) => (
              <tr key={row.product_id}>
                <td className="px-4 py-2">
                  <div className="font-medium text-neutral-900">{row.name}</div>
                  <div className="font-mono text-xs text-neutral-500">{row.sku}</div>
                </td>
                <td className="px-4 py-2 text-neutral-600">{row.category}</td>
                <td className="px-4 py-2 text-right"><StockBadge quantity={row.quantity} /></td>
                <td className="px-4 py-2 text-right tabular-nums">{row.sold_30d}</td>
                <td className="px-4 py-2 text-right tabular-nums">{row.days_of_cover ?? "—"}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Sales by category">
          <Table head={["Category", "Orders", "Units", "Revenue"]}>
            {report.sales_by_category.map((row) => (
              <tr key={row.category_id} className={row.units === 0 ? "text-neutral-400" : ""}>
                <td className="px-4 py-2">
                  {row.category}
                  {row.parent_category && <span className="text-xs text-neutral-400"> · {row.parent_category}</span>}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">{row.orders}</td>
                <td className="px-4 py-2 text-right tabular-nums">{row.units}</td>
                <td className="px-4 py-2 text-right tabular-nums">{money(row.revenue)}</td>
              </tr>
            ))}
          </Table>
          <p className="border-t border-neutral-100 px-4 py-2 text-xs text-neutral-500">
            An order with items in two categories counts once in each.
          </p>
        </Card>

        <Card title="Return rate by category">
          <Table head={["Category", "Sold", "Returned", "Rate"]}>
            {report.return_rate_by_category.map((row) => (
              <tr key={row.category_id} className={row.units_sold === 0 ? "text-neutral-400" : ""}>
                <td className="px-4 py-2">{row.category}</td>
                <td className="px-4 py-2 text-right tabular-nums">{row.units_sold}</td>
                <td className="px-4 py-2 text-right tabular-nums">{row.units_returned}</td>
                <td className="px-4 py-2 text-right tabular-nums">{percent(row.return_rate)}</td>
              </tr>
            ))}
          </Table>
          <p className="border-t border-neutral-100 px-4 py-2 text-xs text-neutral-500">
            Of the units sold in the window, how many came back (rejected returns don&apos;t count). Items have
            30 days to come back, so a recent window reads low.
          </p>
        </Card>
      </div>

      <Card title="Return rate by product">
        {report.return_rate_by_product.length === 0 ? <Empty>Nothing sold in this window.</Empty> : (
          <Table head={["Product", "Sold", "Returned", "Rate"]}>
            {report.return_rate_by_product.map((row) => (
              <tr key={row.product_id}>
                <td className="px-4 py-2">
                  <div className="font-medium text-neutral-900">{row.name}</div>
                  <div className="font-mono text-xs text-neutral-500">{row.sku}</div>
                </td>
                <td className="px-4 py-2 text-right tabular-nums">{row.units_sold}</td>
                <td className="px-4 py-2 text-right tabular-nums">{row.units_returned}</td>
                <td className="px-4 py-2 text-right tabular-nums">{percent(row.return_rate)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}

/** Plan §6 #5: the products in stock at every retail store of a state (relational division). Any staff. */
function StockedEverywherePanel() {
  const [state, setState] = useState<string>("NSW");
  const result = useLoad(`everywhere:${state}`, () =>
    call(api.GET("/api/v1/reports/stocked-in-every-store", { params: { query: { state } } })));
  return (
    <Card className="mt-4" title="In stock at every store of a state"
      actions={
        <select className={`${selectClass} w-28`} value={state} onChange={(e) => setState(e.target.value)}
          aria-label="State">
          {STATES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      }>
      {result.error && <ErrorBox error={result.error} className="m-4" />}
      {result.data && <Division result={result.data} />}
      {!result.data && !result.error && <Empty>Loading…</Empty>}
    </Card>
  );
}

function Division({ result }: { result: StockedEverywhere }) {
  if (result.stores.length === 0) {
    return (
      <p className="p-4 text-sm text-neutral-600">
        {result.state} has no retail stores, so no store lacks any product: all {result.products.length} active
        products qualify (a division by an empty set is vacuously true).
      </p>
    );
  }
  return (
    <div className="p-4 text-sm">
      <p className="mb-3 text-neutral-600">
        In stock at all {result.stores.length} retail stores in {result.state} ({result.stores.map((s) => s.name)
          .join(", ")}): <b>{result.products.length}</b> products.
      </p>
      {result.products.length === 0 ? <p className="text-neutral-500">None.</p> : (
        <ul className="grid gap-x-6 gap-y-1 sm:grid-cols-2 xl:grid-cols-3">
          {result.products.map((p) => (
            <li key={p.product_id} className="truncate">
              {p.name} <span className="font-mono text-xs text-neutral-400">{p.sku}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <div className="p-4">
        <div className="text-xs font-medium uppercase tracking-wide text-neutral-500">{label}</div>
        <div className="mt-1 text-2xl font-semibold tabular-nums text-neutral-900">{value}</div>
      </div>
    </Card>
  );
}

/** A plain table: the first `left` columns are text, the rest are numbers (right-aligned). */
function Table({ head, left = 1, children }: { head: string[]; left?: number; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500">
          <tr>
            {head.map((h, i) => (
              <th key={h} className={`px-4 py-2 font-medium ${i < left ? "" : "text-right"}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-100">{children}</tbody>
      </table>
    </div>
  );
}

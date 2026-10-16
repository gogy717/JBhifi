"use client";

import { type ReactNode, useState } from "react";

import { FilterPills, RuleTag } from "@/components/admin/filters";
import { useStaff } from "@/components/admin/staff-gate";
import { StorePicker } from "@/components/admin/store-select";
import { Cell, ProductName, Row, Table } from "@/components/admin/table";
import { Card, Dot, Empty, ErrorBox, PageHeader, StockBadge } from "@/components/ui";
import { api, call, type StockedEverywhere, type StoreReport } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

const WINDOWS = [7, 30, 90] as const;
const STATES = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"] as const;
// Under two weeks of cover at the recent sales rate: the report lists it as low stock for that reason too.
const SHORT_COVER_DAYS = 14;

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
          snapshot of the database (<code className="font-mono">REPEATABLE READ</code>), so the figures always agree
          with each other.
        </>}
        actions={canRead ? <StorePicker ownStore={isSupport ? undefined : me.store_name ?? undefined}
          stores={stores.data ?? []} value={storeId} onChange={setStoreId} /> : undefined}
      />

      {canRead ? (
        <>
          <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2">
            <span className="text-xs font-semibold uppercase tracking-[0.08em] text-muted">Sales in the last</span>
            <FilterPills label="Sales in the last" value={days} onChange={setDays}
              options={WINDOWS.map((n) => ({ value: n, label: `${n} days` }))} />
            <span className="text-xs text-muted">Low stock always uses the last 30 days&apos; sales rate.</span>
          </div>

          {report.error && <ErrorBox error={report.error} className="mb-5" />}
          {!data && !report.error && <Card><Empty>Loading…</Empty></Card>}
          {data && <ReportSections report={data} loading={report.loading} />}
        </>
      ) : (
        <Card className="mb-5">
          <p className="p-5 text-sm text-muted">
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
  const revenue = Number(total.revenue);
  const lowCount = report.low_stock.length;
  return (
    <div className={`space-y-5 transition-opacity ${loading ? "opacity-60" : ""}`}>
      <p className="text-sm text-muted">
        <b className="font-semibold text-ink">{report.store_name}</b> · sales placed in the {report.days} days to{" "}
        {formatDateTime(report.generated_at)}
      </p>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label="Revenue" value={money(total.revenue)} />
        <Tile label="Orders" value={String(total.orders)} />
        <Tile label="Units sold" value={String(total.units)} />
        <Tile label="Low stock" value={String(lowCount)} warn={lowCount > 0}
          hint={lowCount > 0 ? "products to reorder" : "nothing running low"} />
      </div>

      <Card title={<span className="flex flex-wrap items-center gap-2">
        {lowCount > 0 && <Dot className="bg-warn" />}
        Low stock
        <span className="font-sans font-normal text-muted">
          · 3 or fewer left, or under {SHORT_COVER_DAYS} days at the last 30 days&apos; rate
        </span>
      </span>}>
        {report.low_stock.length === 0 ? <Empty>Nothing is running low.</Empty> : (
          <Table label="Low stock"
            columns={["Product", "Category", { label: "On hand", align: "right" }, { label: "Sold (30 days)", align: "right" },
              { label: "Days of cover", align: "right" }]}>
            {report.low_stock.map((row) => {
              const cover = row.days_of_cover === null ? null : Number(row.days_of_cover);
              return (
                <Row key={row.product_id}>
                  <Cell><ProductName name={row.name} sku={row.sku} /></Cell>
                  <Cell className="text-muted">{row.category}</Cell>
                  <Cell align="right"><StockBadge quantity={row.quantity} /></Cell>
                  <Cell numeric>{row.sold_30d}</Cell>
                  <Cell numeric className={cover !== null && cover < SHORT_COVER_DAYS ? "font-semibold text-warn-ink" : ""}>
                    {row.days_of_cover ?? "—"}
                  </Cell>
                </Row>
              );
            })}
          </Table>
        )}
      </Card>

      <div className="grid items-start gap-5 xl:grid-cols-2">
        <Card title="Sales by category">
          <Table label="Sales by category"
            columns={["Category", { label: "Orders", align: "right" }, { label: "Units", align: "right" },
              { label: "Revenue", align: "right" }]}>
            {report.sales_by_category.map((row) => {
              const share = revenue > 0 ? Number(row.revenue) / revenue : 0;
              return (
                <Row key={row.category_id} className={row.units === 0 ? "text-faint" : ""}>
                  <Cell>
                    <div>
                      {row.category}
                      {row.parent_category && <span className="text-xs text-faint"> · {row.parent_category}</span>}
                    </div>
                    <ShareBar share={share} label={`${(share * 100).toFixed(0)}% of revenue`} />
                  </Cell>
                  <Cell numeric>{row.orders}</Cell>
                  <Cell numeric>{row.units}</Cell>
                  <Cell numeric className={row.units === 0 ? "" : "font-semibold"}>{money(row.revenue)}</Cell>
                </Row>
              );
            })}
          </Table>
          <p className="border-t border-line px-5 py-3 text-xs text-muted">
            An order with items in two categories counts once in each. The bar is the category&apos;s share of the
            store&apos;s revenue.
          </p>
        </Card>

        <Card title="Return rate by category">
          <Table label="Return rate by category"
            columns={["Category", { label: "Sold", align: "right" }, { label: "Returned", align: "right" },
              { label: "Rate", align: "right" }]}>
            {report.return_rate_by_category.map((row) => (
              <Row key={row.category_id} className={row.units_sold === 0 ? "text-faint" : ""}>
                <Cell>{row.category}</Cell>
                <Cell numeric>{row.units_sold}</Cell>
                <Cell numeric>{row.units_returned}</Cell>
                <Cell numeric className="font-semibold">{percent(row.return_rate)}</Cell>
              </Row>
            ))}
          </Table>
          <p className="border-t border-line px-5 py-3 text-xs text-muted">
            Of the units sold in the window, how many came back (rejected returns don&apos;t count). Items have
            30 days to come back, so a recent window reads low.
          </p>
        </Card>
      </div>

      <Card title="Return rate by product">
        {report.return_rate_by_product.length === 0 ? <Empty>Nothing sold in this window.</Empty> : (
          <Table label="Return rate by product"
            columns={["Product", { label: "Sold", align: "right" }, { label: "Returned", align: "right" },
              { label: "Rate", align: "right" }]}>
            {report.return_rate_by_product.map((row) => (
              <Row key={row.product_id}>
                <Cell><ProductName name={row.name} sku={row.sku} /></Cell>
                <Cell numeric>{row.units_sold}</Cell>
                <Cell numeric>{row.units_returned}</Cell>
                <Cell numeric className="font-semibold">{percent(row.return_rate)}</Cell>
              </Row>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}

/** A thin bar for a share between 0 and 1. The figure is in the label, for screen readers and on hover. */
function ShareBar({ share, label }: { share: number; label: string }) {
  return (
    <div role="img" aria-label={label} title={label} className="mt-1.5 h-1.5 w-full max-w-48 rounded-full bg-sand">
      <div className="h-full rounded-full bg-brand" style={{ width: `${Math.round(share * 100)}%` }} />
    </div>
  );
}

/** Plan §6 #5: the products in stock at every retail store of a state (relational division). Any staff. */
function StockedEverywherePanel() {
  const [state, setState] = useState<string>("NSW");
  const result = useLoad(`everywhere:${state}`, () =>
    call(api.GET("/api/v1/reports/stocked-in-every-store", { params: { query: { state } } })));
  return (
    <Card className="mt-5" title={<span className="flex items-center gap-2">
      In stock at every store of a state <RuleTag>relational division</RuleTag>
    </span>}>
      <div className="border-b border-line px-5 py-4">
        <FilterPills label="State" value={state} onChange={setState}
          options={STATES.map((s) => ({ value: s, label: s }))} />
      </div>
      {result.error && <ErrorBox error={result.error} className="m-5" />}
      {result.data && <Division result={result.data} />}
      {!result.data && !result.error && <Empty>Loading…</Empty>}
    </Card>
  );
}

function Division({ result }: { result: StockedEverywhere }) {
  if (result.stores.length === 0) {
    return (
      <p className="p-5 text-sm text-muted">
        {result.state} has no retail stores, so no store lacks any product: all {result.products.length} active
        products qualify (a division by an empty set is vacuously true).
      </p>
    );
  }
  return (
    <div className="p-5 text-sm">
      <p className="mb-4 text-muted">
        In stock at all {result.stores.length} retail stores in {result.state} ({result.stores.map((s) => s.name)
          .join(", ")}): <b className="font-display text-base text-ink">{result.products.length}</b> products.
      </p>
      {result.products.length === 0 ? <p className="text-muted">None.</p> : (
        <ul className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2 xl:grid-cols-3">
          {result.products.map((p) => (
            <li key={p.product_id} className="flex min-w-0 items-baseline gap-2">
              <Dot className="-translate-y-px bg-ok" />
              <span className="truncate">
                {p.name} <span className="font-mono text-xs text-faint">{p.sku}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Tile({ label, value, hint, warn = false }: { label: string; value: string; hint?: ReactNode; warn?: boolean }) {
  return (
    <div className="rounded-card border border-line bg-white px-4 py-3.5">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-muted">
        {warn && <Dot className="bg-warn" />}
        {label}
      </div>
      <div className={`mt-1 font-display text-3xl font-bold leading-tight tabular-nums ${warn ? "text-warn-ink" : "text-ink"}`}>
        {value}
      </div>
      {hint && <div className="text-xs text-muted">{hint}</div>}
    </div>
  );
}

"use client";

import Link from "next/link";
import { useDeferredValue, useState } from "react";

import { RuleTag } from "@/components/admin/filters";
import { SearchIcon } from "@/components/admin/icons";
import { useStaff } from "@/components/admin/staff-gate";
import { Cell, Row, Table } from "@/components/admin/table";
import { ReturnStatusBadge } from "@/components/return-status";
import { StatusBadge } from "@/components/shop/order-timeline";
import { Badge, Card, Empty, ErrorBox, Field, inputClass, PageHeader } from "@/components/ui";
import { api, call, type HistoryEvent, type ReturnSummary } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function SupportPage() {
  const me = useStaff();
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search.trim());
  const [customerId, setCustomerId] = useState<number>();

  if (me.staff_type !== "support") {
    return (
      <>
        <title>Support · TechLight Admin</title>
        <PageHeader title="Support" />
        <Card><p className="p-5 text-sm text-muted">Customer lookup is for support staff.</p></Card>
      </>
    );
  }

  return (
    <>
      <title>Support · TechLight Admin</title>
      <PageHeader
        title="Support"
        description={<>
          Find any customer and see everything that happened to them: their orders, each status change and who
          made it, payments and returns (R10).
        </>}
      />
      <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-[20rem_minmax(0,1fr)]">
        <Card>
          <div className="p-5">
            <Field label="Find a customer" hint="Part of a name or an email address.">
              <span className="relative block">
                <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <input className={`${inputClass} pl-10`} placeholder="e.g. alice or @example.com" value={search}
                  onChange={(e) => setSearch(e.target.value)} />
              </span>
            </Field>
          </div>
          <SearchResults q={q} selected={customerId} onSelect={setCustomerId} />
        </Card>
        {customerId === undefined
          ? <Card><Empty>Search for a customer, then pick one.</Empty></Card>
          : <CustomerFile customerId={customerId} />}
      </div>
    </>
  );
}

function SearchResults({ q, selected, onSelect }: {
  q: string;
  selected?: number;
  onSelect: (id: number) => void;
}) {
  const results = useLoad(`customers:${q}`, () => q.length < 2
    ? Promise.resolve([])
    : call(api.GET("/api/v1/customers", { params: { query: { q } } })));
  if (q.length < 2) return null;
  if (results.error) return <ErrorBox error={results.error} className="m-5" />;
  const rows = results.data ?? [];
  if (rows.length === 0) return <Empty>{results.loading ? "Searching…" : "No customer matches."}</Empty>;
  return (
    <ul className="divide-y divide-line border-t border-line">
      {rows.map((c) => {
        const chosen = c.customer_id === selected;
        return (
          <li key={c.customer_id}>
            <button type="button" onClick={() => onSelect(c.customer_id)} aria-pressed={chosen}
              className={`relative w-full px-5 py-3 text-left text-sm transition-colors focus-visible:outline-none
                focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand ${
                chosen ? "bg-brand-soft" : "hover:bg-canvas"}`}>
              {chosen && <span aria-hidden="true" className="absolute inset-y-2 left-0 w-1 rounded-full bg-brand-strong" />}
              <div className="font-semibold text-ink">{c.full_name}</div>
              <div className="truncate text-xs text-muted">{c.email}</div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function CustomerFile({ customerId }: { customerId: number }) {
  const customer = useLoad(`customer:${customerId}`, () =>
    call(api.GET("/api/v1/customers/{customer_id}", { params: { path: { customer_id: customerId } } })));
  const orders = useLoad(`customer-orders:${customerId}`, () =>
    call(api.GET("/api/v1/customers/{customer_id}/orders", { params: { path: { customer_id: customerId } } })));
  const returns = useLoad(`customer-returns:${customerId}`, () =>
    call(api.GET("/api/v1/customers/{customer_id}/returns", { params: { path: { customer_id: customerId } } })));
  const history = useLoad(`customer-history:${customerId}`, () =>
    call(api.GET("/api/v1/customers/{customer_id}/history", { params: { path: { customer_id: customerId } } })));
  const profile = customer.data;

  return (
    <div className="space-y-5">
      <Card>
        {customer.error && <ErrorBox error={customer.error} className="m-5" />}
        {!profile && !customer.error && <div className="m-5 h-20 animate-pulse rounded-tile bg-sand" />}
        {profile && (
          <div className="grid gap-5 p-5 text-sm sm:grid-cols-2">
            <div>
              <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{profile.full_name}</h2>
              <div className="mt-1 text-[15px]">{profile.email}</div>
              <div className="text-muted">{profile.phone ?? "No phone"}</div>
              <div className="mt-1 text-xs text-muted">Customer since {formatDateTime(profile.created_at)}</div>
            </div>
            <div>
              <div className="mb-1.5 text-xs font-bold uppercase tracking-[0.08em] text-muted">Addresses</div>
              <ul className="space-y-1">
                {profile.addresses.length === 0 && <li className="text-muted">No addresses.</li>}
                {profile.addresses.map((a) => (
                  <li key={a.address_no} className={a.is_active ? "" : "text-muted"}>
                    {a.line1}, {a.suburb} {a.state} {a.postcode} {!a.is_active && <Badge>retired</Badge>}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </Card>

      <Card title={<>Orders {orders.data && <span className="font-sans font-normal text-muted">· {orders.data.length}</span>}</>}>
        {orders.error && <ErrorBox error={orders.error} className="m-5" />}
        {orders.data?.length === 0 && <Empty>No orders yet.</Empty>}
        {orders.data && orders.data.length > 0 && (
          <Table label="The customer's orders"
            columns={["Order", "Placed", "How", "Store", { label: "Total", align: "right" }, "Status"]}>
            {orders.data.map((o) => (
              <Row key={o.order_id}>
                <Cell>
                  <Link href={`/orders/${o.order_id}`}
                    className="font-semibold tabular-nums text-ink hover:text-brand-strong hover:underline">
                    #{o.order_id}
                  </Link>
                </Cell>
                <Cell className="whitespace-nowrap tabular-nums text-muted">{formatDateTime(o.placed_at)}</Cell>
                <Cell className="whitespace-nowrap">{o.fulfilment_method === "delivery" ? "Delivery" : "Click & Collect"}</Cell>
                <Cell className="whitespace-nowrap text-muted">{o.fulfilling_store_name}</Cell>
                <Cell numeric className="font-semibold">{money(o.total)}</Cell>
                <Cell><StatusBadge status={o.status} /></Cell>
              </Row>
            ))}
          </Table>
        )}
      </Card>

      <Card title={<>Returns {returns.data && <span className="font-sans font-normal text-muted">· {returns.data.length}</span>}</>}>
        {returns.error && <ErrorBox error={returns.error} className="m-5" />}
        {returns.data?.length === 0 && <Empty>No returns.</Empty>}
        {returns.data && returns.data.length > 0 && (
          <ul className="divide-y divide-line">
            {returns.data.map((r) => <ReturnRow key={r.return_id} row={r} />)}
          </ul>
        )}
      </Card>

      <Card title="History" actions={<RuleTag>R10</RuleTag>}>
        {history.error && <ErrorBox error={history.error} className="m-5" />}
        {history.data?.length === 0 && <Empty>Nothing has happened yet.</Empty>}
        {history.data && history.data.length > 0 && (
          <ol className="px-5 py-4">
            {history.data.map((event, i) => <HistoryRow key={i} event={event} />)}
          </ol>
        )}
      </Card>
    </div>
  );
}

/** One return as SP3's ReturnSummary describes it: what comes back, what it is worth, where it is up to. */
function ReturnRow({ row }: { row: ReturnSummary }) {
  return (
    <li className="space-y-1.5 px-5 py-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link href={`/admin/returns/${row.return_id}`}
          className="font-semibold text-ink hover:text-brand-strong hover:underline">
          Return #{row.return_id}
        </Link>
        <span className="text-muted">
          from order #{row.order_id} · asked for {formatDateTime(row.requested_at)}
        </span>
        <ReturnStatusBadge status={row.status} />
      </div>
      <ul>
        {row.lines.map((line) => (
          <li key={line.line_no}>
            <span className="tabular-nums text-muted">{line.quantity} ×</span> {line.name}{" "}
            <span className="font-mono text-xs text-faint">{line.sku}</span>
            <span className="text-muted"> at {money(line.unit_price)}</span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-x-4 text-xs text-muted">
        <span>Reason: {row.reason}</span>
        <span>Worth {money(row.value)}</span>
        {row.refunded !== null && <span>Refunded {money(row.refunded)}</span>}
        {row.received_store_name && row.received_at && (
          <span>Received at {row.received_store_name}, {formatDateTime(row.received_at)}</span>
        )}
        {row.rejection_reason && <span className="text-red-700">Rejected: {row.rejection_reason}</span>}
      </div>
    </li>
  );
}

function HistoryRow({ event }: { event: HistoryEvent }) {
  return (
    <li className="group relative flex gap-3 pb-4 last:pb-0">
      <span aria-hidden="true" className="absolute bottom-0 left-[5px] top-4 w-0.5 bg-line group-last:hidden" />
      <span aria-hidden="true" className={`relative z-10 mt-1.5 h-3 w-3 shrink-0 rounded-full ${DOT[event.kind] ?? "bg-muted"}`} />
      <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
        <span className="w-40 shrink-0 text-xs tabular-nums text-muted">{formatDateTime(event.at)}</span>
        <span className="font-semibold">Order #{event.order_id}</span>
        <span>{describe(event)}</span>
      </div>
    </li>
  );
}

// One colour per kind of event: status moves ink, money in green and back out blue, returns amber until they are
// settled (green refunded, red rejected).
const DOT: Record<string, string> = {
  status: "bg-ink", charge: "bg-ok", refund: "bg-sky-600", return_requested: "bg-warn", return_received: "bg-warn",
  return_refunded: "bg-ok", return_rejected: "bg-red-600",
};

function describe(event: HistoryEvent): string {
  switch (event.kind) {
    case "status": {
      const move = event.from_status ? `${event.from_status} → ${event.to_status}` : `placed`;
      return event.staff_name ? `${move}, by ${event.staff_name}` : move;
    }
    case "charge":
      return `charged ${money(event.amount ?? 0)}`;
    case "refund":
      return event.return_id ? `refunded ${money(event.amount ?? 0)} for return #${event.return_id}`
        : `refunded ${money(event.amount ?? 0)}`;
    case "return_requested":
      return `return #${event.return_id} requested`;
    case "return_received":
      return `return #${event.return_id} received${event.staff_name ? `, by ${event.staff_name}` : ""}`;
    case "return_refunded":
      return `return #${event.return_id} refunded${event.staff_name ? `, by ${event.staff_name}` : ""}`;
    case "return_rejected":
      return `return #${event.return_id} rejected${event.staff_name ? ` by ${event.staff_name}` : ""}`
        + (event.note ? `: ${event.note}` : "");
    default:
      return event.kind;
  }
}

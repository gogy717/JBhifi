"use client";

import Link from "next/link";
import { useDeferredValue, useState } from "react";

import { useStaff } from "@/components/admin/staff-gate";
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
        <title>Support · JB Admin</title>
        <PageHeader title="Support" />
        <Card><p className="p-4 text-sm text-neutral-600">Customer lookup is for support staff.</p></Card>
      </>
    );
  }

  return (
    <>
      <title>Support · JB Admin</title>
      <PageHeader
        title="Support"
        description={<>
          Find any customer and see everything that happened to them: their orders, each status change and who
          made it, payments and returns (R10).
        </>}
      />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[20rem_minmax(0,1fr)]">
        <Card>
          <div className="p-4">
            <Field label="Find a customer" hint="Part of a name or an email address.">
              <input className={inputClass} placeholder="e.g. alice or @example.com" value={search}
                onChange={(e) => setSearch(e.target.value)} />
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
  if (results.error) return <ErrorBox error={results.error} className="m-4" />;
  const rows = results.data ?? [];
  if (rows.length === 0) return <Empty>{results.loading ? "Searching…" : "No customer matches."}</Empty>;
  return (
    <ul className="divide-y divide-neutral-100 border-t border-neutral-200">
      {rows.map((c) => (
        <li key={c.customer_id}>
          <button type="button" onClick={() => onSelect(c.customer_id)}
            className={`w-full px-4 py-2 text-left text-sm hover:bg-neutral-50 ${
              c.customer_id === selected ? "bg-yellow-50" : ""}`}>
            <div className="font-medium text-neutral-900">{c.full_name}</div>
            <div className="text-xs text-neutral-500">{c.email}</div>
          </button>
        </li>
      ))}
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
    <div className="space-y-4">
      <Card title={profile ? profile.full_name : "Customer"}>
        {customer.error && <ErrorBox error={customer.error} className="m-4" />}
        {profile && (
          <div className="grid gap-3 p-4 text-sm sm:grid-cols-2">
            <div>
              <div>{profile.email}</div>
              <div className="text-neutral-500">{profile.phone ?? "No phone"}</div>
              <div className="text-xs text-neutral-500">Customer since {formatDateTime(profile.created_at)}</div>
            </div>
            <ul className="space-y-1">
              {profile.addresses.length === 0 && <li className="text-neutral-500">No addresses.</li>}
              {profile.addresses.map((a) => (
                <li key={a.address_no}>
                  {a.line1}, {a.suburb} {a.state} {a.postcode} {!a.is_active && <Badge>retired</Badge>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      <Card title="Orders">
        {orders.error && <ErrorBox error={orders.error} className="m-4" />}
        {orders.data?.length === 0 && <Empty>No orders yet.</Empty>}
        {orders.data && orders.data.length > 0 && (
          <ul className="divide-y divide-neutral-100">
            {orders.data.map((o) => (
              <li key={o.order_id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm">
                <Link href={`/orders/${o.order_id}`} className="font-medium hover:underline">
                  Order #{o.order_id}
                </Link>
                <span className="text-neutral-500">
                  {formatDateTime(o.placed_at)} · {o.fulfilment_method === "delivery" ? "Delivery" : "Click & Collect"}
                  {" "}· {o.fulfilling_store_name}
                </span>
                <span className="tabular-nums">{money(o.total)}</span>
                <StatusBadge status={o.status} />
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Returns">
        {returns.error && <ErrorBox error={returns.error} className="m-4" />}
        {returns.data?.length === 0 && <Empty>No returns.</Empty>}
        {returns.data && returns.data.length > 0 && (
          <ul className="divide-y divide-neutral-100">
            {returns.data.map((r) => <ReturnRow key={r.return_id} row={r} />)}
          </ul>
        )}
      </Card>

      <Card title="History">
        {history.error && <ErrorBox error={history.error} className="m-4" />}
        {history.data?.length === 0 && <Empty>Nothing has happened yet.</Empty>}
        {history.data && history.data.length > 0 && (
          <ol className="divide-y divide-neutral-100">
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
    <li className="space-y-1 px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link href={`/admin/returns/${row.return_id}`} className="font-medium hover:underline">
          Return #{row.return_id}
        </Link>
        <span className="text-neutral-500">
          from order #{row.order_id} · asked for {formatDateTime(row.requested_at)}
        </span>
        <ReturnStatusBadge status={row.status} />
      </div>
      <ul className="text-neutral-700">
        {row.lines.map((line) => (
          <li key={line.line_no}>
            {line.quantity} × {line.name} <span className="font-mono text-xs text-neutral-400">{line.sku}</span>
            <span className="text-neutral-500"> at {money(line.unit_price)}</span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-x-4 text-xs text-neutral-500">
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
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2 text-sm">
      <span className="w-40 shrink-0 text-xs tabular-nums text-neutral-500">{formatDateTime(event.at)}</span>
      <span className="font-medium">Order #{event.order_id}</span>
      <span className="text-neutral-700">{describe(event)}</span>
    </li>
  );
}

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

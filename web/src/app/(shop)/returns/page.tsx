"use client";

import Link from "next/link";

import { ReturnStatusBadge } from "@/components/return-status";
import { CustomerGate } from "@/components/shop/customer-gate";
import { Button, Card, Empty, ErrorBox } from "@/components/ui";
import { api, call, type CustomerDetail, type ReturnSummary } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

export default function ReturnsPage() {
  return (
    <div className="space-y-5">
      <title>My returns · TechLight</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> / My returns
      </nav>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">My returns</h1>
          <p className="mt-1 text-sm text-neutral-600">
            Ask for a return from a delivered or collected order, within 30 days. Bring the items to any TechLight
            store: once they are checked you&apos;re refunded what you paid.
          </p>
        </div>
        <Link href={SHOP_PAGES.orders.href} className="text-sm font-medium hover:underline">My orders →</Link>
      </div>
      <CustomerGate what="see your returns">{(customer) => <Returns customer={customer} />}</CustomerGate>
    </div>
  );
}

function Returns({ customer }: { customer: CustomerDetail }) {
  const customerId = customer.customer_id;
  const returns = useLoad(`returns:${customerId}`, () =>
    call(api.GET("/api/v1/customers/{customer_id}/returns", { params: { path: { customer_id: customerId } } })));

  if (returns.error) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <ErrorBox error={returns.error} />
        <Button onClick={returns.reload}>Try again</Button>
      </div>
    );
  }
  if (!returns.data) return <div className="h-32 animate-pulse rounded-xl bg-neutral-200" />;
  if (returns.data.length === 0) {
    return (
      <Card><Empty>
        No returns yet. To return something, open the order in{" "}
        <Link href={SHOP_PAGES.orders.href} className="font-medium underline">My orders</Link>.
      </Empty></Card>
    );
  }
  // Newest first, as the API lists them.
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {returns.data.map((row) => <ReturnCard key={row.return_id} row={row} />)}
    </div>
  );
}

function ReturnCard({ row }: { row: ReturnSummary }) {
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-neutral-200">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold">Return #{row.return_id}</div>
          <div className="text-xs text-neutral-500">
            Asked for {formatDateTime(row.requested_at)} · from{" "}
            <Link href={`${SHOP_PAGES.orders.href}/${row.order_id}`} className="underline">order #{row.order_id}</Link>
          </div>
        </div>
        <ReturnStatusBadge status={row.status} />
      </div>
      <ul className="mt-3 space-y-0.5 text-sm text-neutral-700">
        {row.lines.map((line) => (
          <li key={line.line_no}>{line.quantity} × {line.name} <span className="text-neutral-500">at {money(line.unit_price)}</span></li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-neutral-500">Your reason: {row.reason}</p>
      <div className="mt-3 text-sm">
        {row.status === "requested" && <>Bring the items to any TechLight store. Worth <b>{money(row.value)}</b>.</>}
        {row.status === "received" && (
          <>Received at {row.received_store_name} on {row.received_at && formatDateTime(row.received_at)}: being checked.</>
        )}
        {row.status === "refunded" && (
          // A return worth nothing is refunded without a payment (there is nothing to pay back).
          <>Refunded <b className="tabular-nums">{money(row.refunded ?? "0")}</b>
            {row.resolved_at && <> on {formatDateTime(row.resolved_at)}</>}.</>
        )}
        {row.status === "rejected" && (
          <span className="text-red-700">
            Not accepted by {row.received_store_name}: {row.rejection_reason}. The items are yours to take back.
          </span>
        )}
      </div>
    </div>
  );
}

"use client";

import Link from "next/link";

import { ReturnStatusBadge } from "@/components/return-status";
import { CustomerGate } from "@/components/shop/customer-gate";
import { Crumbs, focusRing, PageIntro, pillLink, Price, Skeleton } from "@/components/shop/page-parts";
import { ReturnProgress } from "@/components/shop/return-progress";
import { Button, Card, Empty, ErrorBox } from "@/components/ui";
import { api, call, type CustomerDetail, type ReturnSummary } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

export default function ReturnsPage() {
  return (
    <div className="space-y-8">
      <title>My returns · TechLight</title>
      <div className="space-y-4">
        <Crumbs trail={[["Home", "/"], ["My returns"]]} />
        <PageIntro title="My returns"
          actions={<Link href={SHOP_PAGES.orders.href} className={pillLink("outline")}>My orders</Link>}>
          Ask for a return from a delivered or collected order, within 30 days. Bring the items to any TechLight
          store: once they are checked you&apos;re refunded what you paid.
        </PageIntro>
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
  if (!returns.data) return <Skeleton className="h-48" />;
  if (returns.data.length === 0) {
    return (
      <Card><Empty>
        No returns yet. To return something, open the order in{" "}
        <Link href={SHOP_PAGES.orders.href} className="font-bold text-brand-strong underline">My orders</Link>.
      </Empty></Card>
    );
  }
  // Newest first, as the API lists them.
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      {returns.data.map((row) => <ReturnCard key={row.return_id} row={row} />)}
    </div>
  );
}

function ReturnCard({ row }: { row: ReturnSummary }) {
  return (
    <article className="flex flex-col gap-4 rounded-card border border-line bg-white p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-display text-[20px] font-bold tracking-[-0.01em]">Return #{row.return_id}</h2>
          <div className="text-[13px] text-muted">
            Asked for {formatDateTime(row.requested_at)} · from{" "}
            <Link href={`${SHOP_PAGES.orders.href}/${row.order_id}`}
              className={`rounded font-semibold text-brand-strong underline-offset-2 hover:underline ${focusRing}`}>
              order #{row.order_id}
            </Link>
          </div>
        </div>
        <ReturnStatusBadge status={row.status} />
      </div>

      <ReturnProgress status={row.status} />

      <ul className="space-y-1 text-[15px]">
        {row.lines.map((line) => (
          <li key={line.line_no}>
            {line.quantity} × {line.name} <span className="text-muted">at {money(line.unit_price)}</span>
          </li>
        ))}
      </ul>
      <p className="rounded-tile bg-sand px-4 py-2.5 text-[14px] text-muted">
        <span className="font-semibold text-ink">Your reason:</span> {row.reason}
      </p>
      <div className="mt-auto border-t border-line pt-4 text-[15px]">
        {row.status === "requested" && (
          <span className="flex flex-wrap items-baseline justify-between gap-2">
            <span>Bring the items to any TechLight store.</span>
            <span className="flex items-baseline gap-2 text-muted">Worth <Price size="md" value={row.value} /></span>
          </span>
        )}
        {row.status === "received" && (
          <>Received at {row.received_store_name} on {row.received_at && formatDateTime(row.received_at)}: being checked.</>
        )}
        {row.status === "refunded" && (
          // A return worth nothing is refunded without a payment (there is nothing to pay back).
          <span className="flex flex-wrap items-baseline justify-between gap-2">
            <span>Refunded{row.resolved_at && <> on {formatDateTime(row.resolved_at)}</>}.</span>
            <Price size="md" value={row.refunded ?? "0"} />
          </span>
        )}
        {row.status === "rejected" && (
          <span className="text-red-700">
            Not accepted by {row.received_store_name}: {row.rejection_reason}. The items are yours to take back.
          </span>
        )}
      </div>
    </article>
  );
}

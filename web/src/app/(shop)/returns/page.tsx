"use client";

import Link from "next/link";

import { useShop } from "@/components/shop/context";
import { StatusBadge } from "@/components/shop/order-timeline";
import { Button, Card, Empty, ErrorBox } from "@/components/ui";
import { api, call, type ReturnSummary } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function ReturnsPage() {
  const { customer, customerLoading, customerError } = useShop();
  const customerId = customer?.customer_id;
  const returns = useLoad(`returns:${customerId ?? "guest"}`, () =>
    customerId === undefined
      ? Promise.resolve([])
      : call(api.GET("/api/v1/customers/{customer_id}/returns",
        { params: { path: { customer_id: customerId } } })));
  const rows = returns.data ?? [];

  return (
    <div className="space-y-5">
      <title>My returns · JB Hi-Fi</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> / My returns
      </nav>

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">My returns</h1>
          <p className="mt-1 text-sm text-neutral-600">
            Requested → received by the store → refunded. A rejected return stays here so you can see why.
          </p>
        </div>
        <Link href="/orders" className="text-sm font-medium hover:underline">My orders →</Link>
      </div>

      {customerError && <ErrorBox error={customerError} />}
      {customerLoading && <p className="text-sm text-neutral-500">Checking who is signed in…</p>}
      {!customerLoading && !customer && !customerError && (
        <Card><Empty>
          Sign in (demo) on the <Link href="/" className="font-medium underline">home page</Link> to see your
          returns.
        </Empty></Card>
      )}

      {customer && returns.error && (
        <div className="flex flex-wrap items-center gap-3">
          <ErrorBox error={returns.error} />
          <Button onClick={returns.reload}>Try again</Button>
        </div>
      )}
      {customer && !returns.error && !returns.data && <div className="h-32 animate-pulse rounded-xl bg-neutral-200" />}
      {customer && returns.data && rows.length === 0 && (
        <Card><Empty>
          No returns yet. Open a delivered or collected order to start one — the 30-day window is shown
          there.
        </Empty></Card>
      )}

      {rows.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {rows.map((row: ReturnSummary) => (
            <Link key={row.return_id} href={`/orders/${row.order_id}`}
              className="block rounded-xl bg-white p-4 shadow-sm ring-1 ring-neutral-200 transition hover:shadow-md">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-semibold">Return #{row.return_id}</div>
                  <div className="text-xs text-neutral-500">
                    Order #{row.order_id} · {formatDateTime(row.requested_at)}
                  </div>
                </div>
                <StatusBadge status={row.status} />
              </div>
              <p className="mt-2 text-sm text-neutral-700">“{row.reason}”</p>
              <div className="mt-2 text-sm">
                {row.refund_amount
                  ? <span className="font-semibold tabular-nums">{money(row.refund_amount)} refunded</span>
                  : row.status === "refunded"
                    ? <span className="text-neutral-500">Nothing to refund — the items were free</span>
                    : <span className="text-neutral-500">No refund yet</span>}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

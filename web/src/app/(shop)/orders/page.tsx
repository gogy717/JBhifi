"use client";

import Link from "next/link";

import { useShop } from "@/components/shop/context";
import { StatusBadge } from "@/components/shop/order-timeline";
import { Button, Card, Empty, ErrorBox } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function OrdersPage() {
  const { customer, customerLoading, customerError } = useShop();
  const customerId = customer?.customer_id;
  const orders = useLoad(`orders:${customerId ?? "guest"}`, () =>
    customerId === undefined
      ? Promise.resolve([])
      : call(api.GET("/api/v1/customers/{customer_id}/orders", { params: { path: { customer_id: customerId } } })));

  const rows = orders.data ?? [];
  const ready = rows.filter((order) => order.status === "ready");
  const rest = rows.filter((order) => order.status !== "ready");

  return (
    <div className="space-y-5">
      <title>My orders · JB Hi-Fi</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> / My orders
      </nav>

      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">My orders</h1>
        <Link href="/products" className="text-sm font-medium hover:underline">Shop all products →</Link>
      </div>

      {customerError && <ErrorBox error={customerError} />}
      {customerLoading && <p className="text-sm text-neutral-500">Checking who is signed in…</p>}
      {!customerLoading && !customer && !customerError && (
        <Card><Empty>
          Sign in (demo) on the <Link href="/" className="font-medium underline">home page</Link> to see your
          orders.
        </Empty></Card>
      )}

      {customer && orders.error && (
        <div className="flex flex-wrap items-center gap-3">
          <ErrorBox error={orders.error} />
          <Button onClick={orders.reload}>Try again</Button>
        </div>
      )}

      {customer && !orders.error && !orders.data && (
        <div className="h-32 animate-pulse rounded-xl bg-neutral-200" />
      )}

      {customer && orders.data && rows.length === 0 && (
        <Card><Empty>
          No orders yet. <Link href="/products" className="font-medium underline">Start shopping →</Link>
        </Empty></Card>
      )}

      {ready.length > 0 && (
        <section>
          <h2 className="mb-2 text-lg font-semibold tracking-tight">Ready to collect</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {ready.map((order) => <OrderCard key={order.order_id} order={order} highlight />)}
          </div>
        </section>
      )}

      {rest.length > 0 && (
        <section>
          {ready.length > 0 && <h2 className="mb-2 text-lg font-semibold tracking-tight">Earlier orders</h2>}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {rest.map((order) => <OrderCard key={order.order_id} order={order} />)}
          </div>
        </section>
      )}
    </div>
  );
}

function OrderCard({ order, highlight = false }: {
  order: {
    order_id: number; placed_at: string; status: string; fulfilment_method: string;
    fulfilling_store_name: string; total: string; line_count: number;
  };
  highlight?: boolean;
}) {
  return (
    <Link href={`/orders/${order.order_id}`}
      className={`block rounded-xl bg-white p-4 shadow-sm ring-1 transition hover:shadow-md ${
        highlight ? "ring-2 ring-yellow-400" : "ring-neutral-200"}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold">Order #{order.order_id}</div>
          <div className="text-xs text-neutral-500">{formatDateTime(order.placed_at)}</div>
        </div>
        <StatusBadge status={order.status} />
      </div>
      <div className="mt-3 text-sm text-neutral-600">
        {order.line_count} {order.line_count === 1 ? "item" : "items"} ·{" "}
        {order.fulfilment_method === "delivery" ? "Delivery" : "Click & Collect"} ·{" "}
        {order.fulfilling_store_name}
      </div>
      <div className="mt-2 text-lg font-bold tabular-nums">{money(order.total)}</div>
      {highlight && (
        <p className="mt-1 text-xs font-medium text-amber-700">
          <b>{order.fulfilling_store_name}</b> has it ready for you.
        </p>
      )}
    </Link>
  );
}

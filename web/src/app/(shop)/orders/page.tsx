"use client";

import Link from "next/link";

import { CustomerGate } from "@/components/shop/customer-gate";
import { StatusBadge } from "@/components/shop/order-timeline";
import { Button, Card, Empty, ErrorBox } from "@/components/ui";
import { api, call, type CustomerDetail, type OrderSummary } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

export default function OrdersPage() {
  return (
    <div className="space-y-5">
      <title>My orders · TechLight</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> / My orders
      </nav>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">My orders</h1>
        <Link href={SHOP_PAGES.catalogue.href} className="text-sm font-medium hover:underline">
          Shop all products →
        </Link>
      </div>
      <CustomerGate what="see your orders">{(customer) => <Orders customer={customer} />}</CustomerGate>
    </div>
  );
}

function Orders({ customer }: { customer: CustomerDetail }) {
  const customerId = customer.customer_id;
  const orders = useLoad(`orders:${customerId}`, () =>
    call(api.GET("/api/v1/customers/{customer_id}/orders", { params: { path: { customer_id: customerId } } })));

  if (orders.error) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <ErrorBox error={orders.error} />
        <Button onClick={orders.reload}>Try again</Button>
      </div>
    );
  }
  if (!orders.data) return <div className="h-32 animate-pulse rounded-xl bg-neutral-200" />;

  // Newest first, as the API lists them (v_order_summary). useLoad keeps the last result while the next one
  // loads, so keep to this customer's orders.
  const rows = orders.data.filter((order) => order.customer_id === customerId);
  if (rows.length === 0) {
    return (
      <Card><Empty>
        No orders yet. <Link href={SHOP_PAGES.catalogue.href} className="font-medium underline">Start shopping →</Link>
      </Empty></Card>
    );
  }
  const ready = rows.filter((order) => order.status === "ready");
  const rest = rows.filter((order) => order.status !== "ready");

  return (
    <>
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
    </>
  );
}

function OrderCard({ order, highlight = false }: { order: OrderSummary; highlight?: boolean }) {
  return (
    <Link href={`${SHOP_PAGES.orders.href}/${order.order_id}`}
      className={`block rounded-xl bg-white p-4 shadow-sm ring-1 transition hover:shadow-md ${
        highlight ? "ring-2 ring-brand" : "ring-neutral-200"}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold">Order #{order.order_id}</div>
          <div className="text-xs text-neutral-500">
            {formatDateTime(order.placed_at)}
            {order.last_updated_at !== order.placed_at && <> · updated {formatDateTime(order.last_updated_at)}</>}
          </div>
        </div>
        <StatusBadge status={order.status} />
      </div>
      <div className="mt-3 text-sm text-neutral-600">
        {order.line_count} {order.line_count === 1 ? "item" : "items"} ·{" "}
        {order.fulfilment_method === "delivery" ? "Delivery" : "Click & Collect"} · {order.fulfilling_store_name}
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

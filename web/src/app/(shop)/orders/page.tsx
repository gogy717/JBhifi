"use client";

import Link from "next/link";

import { CustomerGate } from "@/components/shop/customer-gate";
import { StatusBadge } from "@/components/shop/order-timeline";
import { Crumbs, focusRing, PageIntro, pillLink, Price, SectionTitle, Skeleton } from "@/components/shop/page-parts";
import { Button, Card, Empty, ErrorBox } from "@/components/ui";
import { api, call, type CustomerDetail, type OrderSummary } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

export default function OrdersPage() {
  return (
    <div className="space-y-8">
      <title>My orders · TechLight</title>
      <div className="space-y-4">
        <Crumbs trail={[["Home", "/"], ["My orders"]]} />
        <PageIntro title="My orders"
          actions={<Link href={SHOP_PAGES.catalogue.href} className={pillLink("outline")}>Shop all products</Link>}>
          Every order you have placed, newest first. Open one to follow it, cancel it or return items.
        </PageIntro>
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
  if (!orders.data) return <Skeleton className="h-40" />;

  // Newest first, as the API lists them (v_order_summary). useLoad keeps the last result while the next one
  // loads, so keep to this customer's orders.
  const rows = orders.data.filter((order) => order.customer_id === customerId);
  if (rows.length === 0) {
    return (
      <Card><Empty>
        No orders yet.{" "}
        <Link href={SHOP_PAGES.catalogue.href} className="font-bold text-brand-strong underline">Start shopping →</Link>
      </Empty></Card>
    );
  }
  const ready = rows.filter((order) => order.status === "ready");
  const rest = rows.filter((order) => order.status !== "ready");

  return (
    <div className="space-y-14">
      {ready.length > 0 && (
        <section>
          <SectionTitle>Ready to collect</SectionTitle>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {ready.map((order) => <OrderCard key={order.order_id} order={order} highlight />)}
          </div>
        </section>
      )}
      {rest.length > 0 && (
        <section>
          {ready.length > 0 ? <SectionTitle>Earlier orders</SectionTitle> : <h2 className="sr-only">Your orders</h2>}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {rest.map((order) => <OrderCard key={order.order_id} order={order} />)}
          </div>
        </section>
      )}
    </div>
  );
}

/** One order as a card. An order waiting at the store is the dark card, like the homepage's store panel. */
function OrderCard({ order, highlight = false }: { order: OrderSummary; highlight?: boolean }) {
  const muted = highlight ? "text-on-ink-muted" : "text-muted";
  return (
    <Link href={`${SHOP_PAGES.orders.href}/${order.order_id}`}
      className={`flex flex-col gap-4 rounded-card p-5 transition-colors ${focusRing} ${highlight
        ? "bg-ink text-white hover:bg-ink/90"
        : "border border-line bg-white hover:border-ink"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {highlight && (
            <span className="mb-1 block text-[12px] font-bold tracking-[0.08em] text-ember uppercase">
              Ready at {order.fulfilling_store_name}
            </span>
          )}
          <div className="font-display text-[20px] font-bold tracking-[-0.01em]">Order #{order.order_id}</div>
          <div className={`text-[13px] ${muted}`}>
            {formatDateTime(order.placed_at)}
            {order.last_updated_at !== order.placed_at && <> · updated {formatDateTime(order.last_updated_at)}</>}
          </div>
        </div>
        <StatusBadge status={order.status} />
      </div>
      <div className={`text-[15px] ${highlight ? "text-on-ink" : "text-muted"}`}>
        {order.line_count} {order.line_count === 1 ? "item" : "items"} ·{" "}
        {order.fulfilment_method === "delivery" ? "Delivery" : "Click & Collect"} · {order.fulfilling_store_name}
      </div>
      <div className={`mt-auto flex items-end justify-between gap-3 border-t pt-4 ${highlight ? "border-white/15" : "border-line"}`}>
        <Price size="lg" value={order.total} />
        <span className={`text-[14px] font-bold ${highlight ? "text-white" : "text-brand-strong"}`}>
          View order <span aria-hidden="true">→</span>
        </span>
      </div>
      {highlight && (
        <p className="text-[14px] text-on-ink">
          <b className="text-white">{order.fulfilling_store_name}</b> has it ready for you.
        </p>
      )}
    </Link>
  );
}

"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { CancelOrder } from "@/components/shop/cancel-order";
import { SignedInGate } from "@/components/shop/customer-gate";
import { NextStatuses, OrderTimeline, StatusBadge } from "@/components/shop/order-timeline";
import { ReturnRequestForm } from "@/components/shop/return-request-form";
import { Button, Card, Empty, ErrorBox } from "@/components/ui";
import { api, call, type Me } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

export default function OrderPage() {
  const { id } = useParams<{ id: string }>();
  const orderId = Number(id);
  const valid = Number.isInteger(orderId) && orderId > 0;

  return (
    <div className="space-y-5">
      <title>{valid ? `Order #${orderId} · JB Hi-Fi` : "Order · JB Hi-Fi"}</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> /{" "}
        <Link href={SHOP_PAGES.orders.href} className="hover:underline">My orders</Link> / {valid ? `#${orderId}` : "…"}
      </nav>
      {valid
        ? <SignedInGate what="see this order">{(me) => <Order orderId={orderId} me={me} />}</SignedInGate>
        : (
          <Card><Empty>
            That isn&apos;t an order number.{" "}
            <Link href={SHOP_PAGES.orders.href} className="underline">Back to My orders</Link>.
          </Empty></Card>
        )}
    </div>
  );
}

function Order({ orderId, me }: { orderId: number; me: Me }) {
  // Whoever is signed in asks, and the API decides: customers see their own orders, store staff their store's,
  // support every order. A refusal comes before "not found", so it doesn't reveal which orders exist.
  const order = useLoad(`order:${orderId}:${me.kind}:${me.id}`, () =>
    call(api.GET("/api/v1/orders/{order_id}", { params: { path: { order_id: orderId } } })));
  // useLoad keeps the last result while the next one loads: never show another order under this number.
  const detail = order.data?.order_id === orderId ? order.data : undefined;

  if (order.error) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <ErrorBox error={order.error} />
        <Button onClick={order.reload}>Try again</Button>
      </div>
    );
  }
  if (!detail) return <div className="h-40 animate-pulse rounded-xl bg-neutral-200" />;

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Order #{detail.order_id}</h1>
          <p className="mt-1 text-sm text-neutral-600">
            Placed {formatDateTime(detail.placed_at)} ·{" "}
            {detail.fulfilment_method === "delivery"
              ? <>Delivery from {detail.fulfilling_store_name}</>
              : <>Click &amp; Collect from {detail.fulfilling_store_name}</>}
          </p>
          <NextStatuses statuses={detail.allowed_next_statuses} />
          <CancelOrder order={detail} me={me} onDone={order.reload} />
        </div>
        <StatusBadge status={detail.status} />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card title="Items" actions={<span className="text-xs text-neutral-500">prices as sold (BR08)</span>}>
          <ul className="divide-y divide-neutral-100">
            {detail.lines.map((line) => (
              <li key={line.line_no} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div>
                  <Link href={`${SHOP_PAGES.catalogue.href}/${line.product_id}`} className="font-medium hover:underline">
                    {line.name}
                  </Link>
                  <div className="font-mono text-xs text-neutral-500">{line.sku}</div>
                </div>
                <div className="text-right text-sm">
                  <div className="tabular-nums">{money(line.unit_price)} × {line.quantity}</div>
                  <div className="font-semibold tabular-nums">{money(line.line_total)}</div>
                </div>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between border-t border-neutral-200 px-4 py-3">
            <span className="text-sm text-neutral-600">Order total</span>
            <span className="text-lg font-bold tabular-nums">{money(detail.total)}</span>
          </div>
        </Card>

        <div className="space-y-5">
          <Card title="Timeline" actions={<span className="text-xs text-neutral-500">R11</span>}>
            <OrderTimeline history={detail.history} />
          </Card>

          <Card title="Where it is going">
            <div className="px-4 py-3 text-sm">
              {detail.delivery_address
                ? (
                  <>
                    <div className="font-medium">{detail.delivery_address.line1}</div>
                    <div className="text-neutral-600">
                      {detail.delivery_address.suburb} {detail.delivery_address.state}{" "}
                      {detail.delivery_address.postcode}
                    </div>
                    <p className="mt-2 text-xs text-neutral-500">
                      Address #{detail.delivery_address.address_no}, as it was when the order was placed: addresses
                      are never edited (BR16).
                    </p>
                  </>
                )
                : <p className="text-neutral-600">Collect from <b>{detail.fulfilling_store_name}</b>. Bring your order number.</p>}
            </div>
          </Card>

          <Card title="Payment (simulated)" actions={<span className="text-xs text-neutral-500">BR14, BR20</span>}>
            <dl className="divide-y divide-neutral-100 text-sm">
              <Amount label="Charged" value={detail.payment.charged} />
              <Amount label="Refunded" value={detail.payment.refunded} />
              <Amount label="Balance (charged − refunded)" value={detail.payment.balance} strong />
            </dl>
          </Card>

          <ReturnRequestForm order={detail} me={me} />
        </div>
      </div>
    </>
  );
}

/** Money from the API (a decimal string, from the v_order_payment view): formatted, never added up here. */
function Amount({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-2.5">
      <dt className="text-neutral-600">{label}</dt>
      <dd className={`tabular-nums ${strong ? "font-semibold" : ""}`}>{money(value)}</dd>
    </div>
  );
}

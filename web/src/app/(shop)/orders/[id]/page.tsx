"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { CancelOrder } from "@/components/shop/cancel-order";
import { SignedInGate } from "@/components/shop/customer-gate";
import { NextStatuses, OrderTimeline, StatusBadge } from "@/components/shop/order-timeline";
import { Crumbs, DetailRow, Eyebrow, Price, SectionTitle, Skeleton } from "@/components/shop/page-parts";
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
    <div className="space-y-8">
      <title>{valid ? `Order #${orderId} · TechLight` : "Order · TechLight"}</title>
      <Crumbs trail={[["Home", "/"], ["My orders", SHOP_PAGES.orders.href], [valid ? `#${orderId}` : "…"]]} />
      {valid
        ? <SignedInGate what="see this order">{(me) => <Order orderId={orderId} me={me} />}</SignedInGate>
        : (
          <Card><Empty>
            That isn&apos;t an order number.{" "}
            <Link href={SHOP_PAGES.orders.href} className="font-bold text-brand-strong underline">Back to My orders</Link>.
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
  if (!detail) return <Skeleton className="h-64" />;

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="min-w-0 space-y-2">
          <Eyebrow>{detail.fulfilment_method === "delivery" ? "Delivery" : "Click & Collect"}</Eyebrow>
          <h1 className="font-display text-[32px] leading-[1.1] font-bold tracking-[-0.025em] sm:text-[40px]">
            Order #{detail.order_id}
          </h1>
          <p className="text-[15px] text-muted">
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

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-8">
          <section>
            <SectionTitle aside={<span className="text-[13px] text-muted">prices as sold (BR08)</span>}>Items</SectionTitle>
            <Card>
              <ul className="divide-y divide-line">
                {detail.lines.map((line) => (
                  <li key={line.line_no} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
                    <div className="min-w-0">
                      <Link href={`${SHOP_PAGES.catalogue.href}/${line.product_id}`}
                        className="font-semibold hover:text-brand-strong">
                        {line.name}
                      </Link>
                      <div className="font-mono text-[12px] text-muted">{line.sku}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-[13px] text-muted tabular-nums">{money(line.unit_price)} × {line.quantity}</div>
                      <div className="font-bold tabular-nums">{money(line.line_total)}</div>
                    </div>
                  </li>
                ))}
              </ul>
              <div className="flex items-baseline justify-between gap-3 border-t border-line px-5 py-4">
                <span className="text-[15px] font-semibold">Order total</span>
                <Price size="lg" value={detail.total} />
              </div>
            </Card>
          </section>

          <section>
            <SectionTitle aside={<span className="text-[13px] text-muted">R11</span>}>Timeline</SectionTitle>
            <Card><OrderTimeline history={detail.history} /></Card>
          </section>
        </div>

        <div className="min-w-0 space-y-5">
          <Card title="Where it is going">
            <div className="px-5 py-4 text-[15px]">
              {detail.delivery_address
                ? (
                  <>
                    <div className="font-bold">{detail.delivery_address.line1}</div>
                    <div className="text-muted">
                      {detail.delivery_address.suburb} {detail.delivery_address.state}{" "}
                      {detail.delivery_address.postcode}
                    </div>
                    <p className="mt-2 text-[13px] text-muted">
                      Address #{detail.delivery_address.address_no}, as it was when the order was placed: addresses
                      are never edited (BR16).
                    </p>
                  </>
                )
                : <p className="text-muted">Collect from <b className="text-ink">{detail.fulfilling_store_name}</b>. Bring your order number.</p>}
            </div>
          </Card>

          <Card title="Payment (simulated)" actions={<span className="text-[13px] text-muted">BR14, BR20</span>}>
            <dl className="divide-y divide-line">
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
  return <DetailRow label={label} strong={strong}><span className="tabular-nums">{money(value)}</span></DetailRow>;
}

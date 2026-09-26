"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { OrderTimeline, StatusBadge } from "@/components/shop/order-timeline";
import { ReturnRequestForm } from "@/components/shop/return-request-form";
import { Button, Card, Empty, ErrorBox } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function OrderPage() {
  const params = useParams<{ id: string }>();
  const [requested, setRequested] = useState<{ return_id: number; refund_preview: string }>();
  const order = useLoad(`order:${params.id}`, () =>
    call(api.GET("/api/v1/orders/{order_id}", { params: { path: { order_id: Number(params.id) } } })));

  const detail = order.data;
  const charged = (detail?.payments ?? []).filter((payment) => payment.kind === "charge")
    .reduce((total, payment) => total + Number(payment.amount), 0);
  const refunded = (detail?.payments ?? []).filter((payment) => payment.kind === "refund")
    .reduce((total, payment) => total + Number(payment.amount), 0);

  return (
    <div className="space-y-5">
      <title>{detail ? `Order #${detail.order_id} · JB Hi-Fi` : "Order · JB Hi-Fi"}</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> /{" "}
        <Link href="/orders" className="hover:underline">My orders</Link> / {detail ? `#${detail.order_id}` : "…"}
      </nav>

      {order.error && (
        <div className="flex flex-wrap items-center gap-3">
          <ErrorBox error={order.error} />
          <Button onClick={order.reload}>Try again</Button>
        </div>
      )}
      {!order.error && !detail && <div className="h-40 animate-pulse rounded-xl bg-neutral-200" />}

      {detail && (
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
            </div>
            <StatusBadge status={detail.status} />
          </div>

          {requested && (
            <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
              Return #{requested.return_id} requested — {money(requested.refund_preview)} if it is accepted.{" "}
              <Link href="/returns" className="font-medium underline">Track your returns →</Link>
            </p>
          )}

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <div className="space-y-5">
              <Card title="What you bought" actions={<span className="text-xs text-neutral-500">BR08</span>}>
                <ul className="divide-y divide-neutral-100">
                  {detail.lines.map((line) => (
                    <li key={line.line_no} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                      <div>
                        <Link href={`/products/${line.product_id}`} className="font-medium hover:underline">
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

              <Card title="Request a return" actions={
                <span className="text-xs text-neutral-500">
                  {detail.return_eligibility.eligible ? "Open" : "Closed"}
                </span>}>
                <ReturnRequestForm order={detail} onRequested={(created) => {
                  setRequested({ return_id: created.return_id, refund_preview: String(created.refund_preview) });
                  order.reload();
                }} />
              </Card>
            </div>

            <div className="space-y-5">
              <Card title="Timeline" actions={<span className="text-xs text-neutral-500">R11</span>}>
                <OrderTimeline history={detail.history} />
              </Card>

              <Card title="Where it is going">
                <div className="px-4 py-3 text-sm">
                  {detail.fulfilment_method === "delivery" && detail.delivery_address
                    ? (
                      <>
                        <div className="font-medium">{detail.delivery_address.line1}</div>
                        <div className="text-neutral-600">
                          {detail.delivery_address.suburb} {detail.delivery_address.state}{" "}
                          {detail.delivery_address.postcode}
                        </div>
                        <p className="mt-2 text-xs text-neutral-500">
                          Address #{detail.delivery_address.address_no} is the one the order was placed with;
                          addresses are never edited (BR16).
                        </p>
                      </>
                    )
                    : (
                      <p className="text-neutral-600">
                        Collect from <b>{detail.fulfilling_store_name}</b>. Bring your order number.
                      </p>
                    )}
                </div>
              </Card>

              <Card title="Payments (simulated)">
                {detail.payments.length === 0
                  ? <Empty>Nothing was charged for this order.</Empty>
                  : (
                    <>
                      <ul className="divide-y divide-neutral-100">
                        {detail.payments.map((payment) => (
                          <li key={payment.payment_id}
                            className="flex items-center justify-between px-4 py-2.5 text-sm">
                            <span>
                              {payment.kind === "charge" ? "Charged" : "Refunded"}
                              <span className="ml-2 text-xs text-neutral-500">
                                {formatDateTime(payment.created_at)}
                              </span>
                            </span>
                            <span className="tabular-nums">{money(payment.amount)}</span>
                          </li>
                        ))}
                      </ul>
                      <div className="flex items-center justify-between border-t border-neutral-200 px-4 py-3 text-sm">
                        <span className="text-neutral-600">Net</span>
                        <span className="font-semibold tabular-nums">{money(String(charged - refunded))}</span>
                      </div>
                    </>
                  )}
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { OrderActions } from "@/components/admin/order-actions";
import { OrderTimeline, StatusBadge } from "@/components/shop/order-timeline";
import { Button, Card, Empty, ErrorBox, PageHeader } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function AdminOrderPage() {
  const params = useParams<{ id: string }>();
  // Keyed by the route, so a late reply for another order can never be written onto this one.
  const orderKey = `admin-order:${params.id}`;
  const order = useLoad(orderKey, () =>
    call(api.GET("/api/v1/orders/{order_id}", { params: { path: { order_id: Number(params.id) } } })));

  const detail = order.data;
  const captured = (detail?.payments ?? []).filter((payment) => payment.kind === "charge")
    .reduce((total, payment) => total + Number(payment.amount), 0);
  const refunded = (detail?.payments ?? []).filter((payment) => payment.kind === "refund")
    .reduce((total, payment) => total + Number(payment.amount), 0);

  return (
    <>
      <title>{detail ? `Order #${detail.order_id} · JB Admin` : "Order · JB Admin"}</title>
      <nav aria-label="Breadcrumb" className="mb-3 text-sm text-neutral-500">
        <Link href="/admin/orders" className="hover:underline">Order queue</Link> /{" "}
        {detail ? `#${detail.order_id}` : "…"}
      </nav>

      {order.error && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <ErrorBox error={order.error} />
          <Button onClick={order.reload}>Try again</Button>
        </div>
      )}
      {!order.error && !detail && <div className="h-40 animate-pulse rounded-xl bg-neutral-200" />}

      {detail && (
        <>
          <PageHeader
            title={`Order #${detail.order_id}`}
            description={<>
              Customer {detail.customer_id} · placed {formatDateTime(detail.placed_at)} ·{" "}
              {detail.fulfilment_method === "delivery" ? "Delivery" : "Click & Collect"} from{" "}
              {detail.fulfilling_store_name}
            </>}
            actions={<StatusBadge status={detail.status} />}
          />

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <div className="space-y-4">
              <Card title="Next step">
                <div className="p-4">
                  <OrderActions order={detail} onChanged={(updated) => order.setData(orderKey, () => updated)} />
                </div>
              </Card>

              <Card title="What to pick and send">
                <ul className="divide-y divide-neutral-100">
                  {detail.lines.map((line) => (
                    <li key={line.line_no} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                      <div>
                        <div className="font-medium">{line.name}</div>
                        <div className="font-mono text-xs text-neutral-500">
                          {line.sku} · sold at {money(line.unit_price)}
                        </div>
                      </div>
                      <div className="text-right text-sm">
                        <div className="text-lg font-semibold tabular-nums">× {line.quantity}</div>
                        <div className="text-xs text-neutral-500 tabular-nums">{money(line.line_total)}</div>
                      </div>
                    </li>
                  ))}
                </ul>
                <div className="flex items-center justify-between border-t border-neutral-200 px-4 py-3">
                  <span className="text-sm text-neutral-600">Order total</span>
                  <span className="text-lg font-bold tabular-nums">{money(detail.total)}</span>
                </div>
              </Card>

              <Card title="Timeline">
                <OrderTimeline history={detail.history} />
              </Card>
            </div>

            <div className="space-y-4">
              <Card title="Deliver or collect">
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
                          The address the order was placed with (BR16: never edited).
                        </p>
                      </>
                    )
                    : <p className="text-neutral-600">Collect from {detail.fulfilling_store_name}.</p>}
                </div>
              </Card>

              <Card title="Money">
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
                                {payment.return_id ? `return #${payment.return_id}` : ""}
                                {payment.cancellation_id ? `cancellation #${payment.cancellation_id}` : ""}
                              </span>
                            </span>
                            <span className="tabular-nums">{money(payment.amount)}</span>
                          </li>
                        ))}
                      </ul>
                      <div className="flex items-center justify-between border-t border-neutral-200 px-4 py-3 text-sm">
                        <span className="text-neutral-600">Still captured</span>
                        <span className="font-semibold tabular-nums">{money(String(captured - refunded))}</span>
                      </div>
                    </>
                  )}
              </Card>

              <Card title="Returns on this order">
                {detail.return_eligibility.lines.length === 0
                  ? <Empty>No lines.</Empty>
                  : (
                    <ul className="divide-y divide-neutral-100 text-sm">
                      {detail.return_eligibility.lines.map((line) => (
                        <li key={line.line_no} className="flex justify-between gap-3 px-4 py-2.5">
                          <span>{line.name}</span>
                          <span className="tabular-nums text-neutral-600">
                            {line.returned_quantity} of {line.quantity} returned
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                <p className="border-t border-neutral-200 px-4 py-3 text-xs text-neutral-500">
                  {detail.return_eligibility.eligible
                    ? `Returnable until ${new Date(detail.return_eligibility.deadline ?? "").toLocaleDateString("en-AU")}.`
                    : detail.return_eligibility.reason}
                </p>
                <div className="border-t border-neutral-200 px-4 py-3">
                  <Link href="/admin/returns" className="text-sm font-medium hover:underline">
                    Returns desk →
                  </Link>
                </div>
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  );
}

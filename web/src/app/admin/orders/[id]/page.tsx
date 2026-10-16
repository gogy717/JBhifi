"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useStaff } from "@/components/admin/staff-gate";
import { ORDER_STATUS_TEXT, OrderTimeline, StatusBadge } from "@/components/shop/order-timeline";
import { Button, Card, Empty, ErrorBox, NoticeBanner, PageHeader, useNotice } from "@/components/ui";
import {
  type ApiError, api, call, type OrderDetail, type OrderStatus, type StaffMove, toApiError,
} from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

// The forward moves staff make, in path order, with what the button says.
const MOVES: Record<StaffMove, string> = {
  picking: "Start picking",
  ready: "Ready for collection",
  shipped: "Mark shipped",
  collected: "Mark collected",
  delivered: "Mark delivered",
};

function isMove(status: string): status is StaffMove {
  return status in MOVES;
}

export default function AdminOrderPage() {
  const { id } = useParams<{ id: string }>();
  const orderId = Number(id);
  if (!Number.isInteger(orderId) || orderId <= 0) {
    return <Card><Empty>That isn&apos;t an order number. <Link href="/admin/orders" className="underline">Back to orders</Link>.</Empty></Card>;
  }
  return <Order orderId={orderId} />;
}

function Order({ orderId }: { orderId: number }) {
  const me = useStaff();
  const order = useLoad(`admin-order:${orderId}`, () =>
    call(api.GET("/api/v1/orders/{order_id}", { params: { path: { order_id: orderId } } })));
  const detail = order.data?.order_id === orderId ? order.data : undefined;
  const { notice, showError, showSuccess, clear } = useNotice();
  const [busy, setBusy] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);

  /** One request that changes the order. The answer is the order as it is now; status_changed means someone else
   *  moved it first, so the page reloads to show where it is. */
  async function act(request: () => Promise<OrderDetail>, done: (after: OrderDetail) => string) {
    setBusy(true);
    clear();
    try {
      const after = await request();
      order.setData(() => after);
      showSuccess(done(after));
    } catch (error) {
      const failure: ApiError = toApiError(error);
      showError(failure);
      if (failure.code === "status_changed") order.reload();
    } finally {
      setBusy(false);
      setConfirmCancel(false);
    }
  }

  function move(current: OrderDetail, to: StaffMove) {
    return act(
      () => call(api.POST("/api/v1/orders/{order_id}/status", {
        params: { path: { order_id: orderId } },
        body: { from_status: current.status as OrderStatus, to_status: to },
      })),
      (after) => `Order #${after.order_id} is now ${ORDER_STATUS_TEXT[after.status].toLowerCase()}.`,
    );
  }

  function cancel(current: OrderDetail) {
    return act(
      () => call(api.POST("/api/v1/orders/{order_id}/cancel", {
        params: { path: { order_id: orderId } },
        body: { from_status: current.status as OrderStatus },
      })),
      (after) => `Order #${after.order_id} is cancelled: its stock is back and ${money(after.payment.refunded)} was refunded.`,
    );
  }

  if (order.error) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <ErrorBox error={order.error} />
        <Button onClick={order.reload}>Try again</Button>
      </div>
    );
  }
  if (!detail) return <div className="h-40 animate-pulse rounded-xl bg-neutral-200" />;

  const moves = detail.allowed_next_statuses.filter(isMove);
  // Support staff move orders along but never cancel them (spec §1); the API says so too.
  const canCancel = detail.allowed_next_statuses.includes("cancelled") && me.staff_type === "store";

  return (
    <>
      <title>{`Order #${detail.order_id} · TechLight Admin`}</title>
      <nav aria-label="Breadcrumb" className="mb-2 text-sm text-neutral-500">
        <Link href="/admin/orders" className="hover:underline">Orders</Link> / #{detail.order_id}
      </nav>
      <PageHeader
        title={`Order #${detail.order_id}`}
        description={<>Placed {formatDateTime(detail.placed_at)} ·{" "}
          {detail.fulfilment_method === "delivery" ? "Delivery from " : "Click & Collect at "}
          {detail.fulfilling_store_name}</>}
        actions={<StatusBadge status={detail.status} />}
      />
      <NoticeBanner notice={notice} onClose={clear} />

      <Card title="Next step" className="mb-5"
        actions={<span className="text-xs text-neutral-500">BR09 decides which moves are allowed</span>}>
        <div className="flex flex-wrap items-center gap-2 px-4 py-3">
          {moves.map((to) => (
            <Button key={to} tone="primary" disabled={busy} onClick={() => move(detail, to)}>{MOVES[to]}</Button>
          ))}
          {canCancel && !confirmCancel && (
            <Button tone="ghost" disabled={busy} onClick={() => setConfirmCancel(true)}>Cancel order…</Button>
          )}
          {canCancel && confirmCancel && (
            <span className="flex flex-wrap items-center gap-2 text-sm">
              Put the items back in stock and refund {money(detail.payment.balance)}?
              <Button tone="danger" disabled={busy} onClick={() => cancel(detail)}>Yes, cancel it</Button>
              <Button disabled={busy} onClick={() => setConfirmCancel(false)}>Keep it</Button>
            </span>
          )}
          {moves.length === 0 && !canCancel && (
            <p className="text-sm text-neutral-600">Nothing more to do: this order is {ORDER_STATUS_TEXT[detail.status].toLowerCase()}.</p>
          )}
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card title="Items to pick">
          <ul className="divide-y divide-neutral-100">
            {detail.lines.map((line) => (
              <li key={line.line_no} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div>
                  <div className="font-medium">{line.name}</div>
                  <div className="font-mono text-xs text-neutral-500">{line.sku}</div>
                </div>
                <div className="text-right text-sm tabular-nums">
                  <div className="font-semibold">× {line.quantity}</div>
                  <div className="text-neutral-500">{money(line.line_total)}</div>
                </div>
              </li>
            ))}
          </ul>
          {detail.delivery_address && (
            <p className="border-t border-neutral-200 px-4 py-3 text-sm text-neutral-600">
              Ship to {detail.delivery_address.line1}, {detail.delivery_address.suburb} {detail.delivery_address.state}{" "}
              {detail.delivery_address.postcode}
            </p>
          )}
        </Card>

        <div className="space-y-5">
          <Card title="Timeline" actions={<span className="text-xs text-neutral-500">R11</span>}>
            <OrderTimeline history={detail.history} />
          </Card>
          <Card title="Payment (simulated)" actions={<span className="text-xs text-neutral-500">BR14, BR20, BR21</span>}>
            <dl className="divide-y divide-neutral-100 text-sm">
              {([["Charged", detail.payment.charged], ["Refunded", detail.payment.refunded],
                ["Held (charged − refunded)", detail.payment.balance]] as const).map(([label, value]) => (
                <div key={label} className="flex items-center justify-between gap-4 px-4 py-2.5">
                  <dt className="text-neutral-600">{label}</dt>
                  <dd className="tabular-nums">{money(value)}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      </div>
    </>
  );
}

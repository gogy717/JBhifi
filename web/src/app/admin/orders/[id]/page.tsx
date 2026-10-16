"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { RuleTag } from "@/components/admin/filters";
import { FulfilmentPath } from "@/components/admin/fulfilment-path";
import { CollectIcon, DeliveryIcon } from "@/components/admin/icons";
import { isMove, MOVES } from "@/components/admin/order-moves";
import { useStaff } from "@/components/admin/staff-gate";
import { Cell, Row, Table } from "@/components/admin/table";
import { ORDER_STATUS_TEXT, OrderTimeline, StatusBadge } from "@/components/shop/order-timeline";
import { Button, Card, Empty, ErrorBox, NoticeBanner, PageHeader, useNotice } from "@/components/ui";
import {
  type ApiError, api, call, type OrderDetail, type OrderStatus, type StaffMove, toApiError,
} from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

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
  if (!detail) return <div className="h-40 animate-pulse rounded-card bg-sand" />;

  const moves = detail.allowed_next_statuses.filter(isMove);
  // Support staff move orders along but never cancel them (spec §1); the API says so too.
  const canCancel = detail.allowed_next_statuses.includes("cancelled") && me.staff_type === "store";
  const delivery = detail.fulfilment_method === "delivery";
  const units = detail.lines.reduce((sum, line) => sum + line.quantity, 0);

  return (
    <>
      <title>{`Order #${detail.order_id} · TechLight Admin`}</title>
      <nav aria-label="Breadcrumb" className="mb-3 text-sm text-muted">
        <Link href="/admin/orders" className="font-semibold text-brand-strong hover:underline">Orders</Link>
        <span aria-hidden="true"> / </span>#{detail.order_id}
      </nav>
      <PageHeader
        title={`Order #${detail.order_id}`}
        description={<span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
          {delivery ? <DeliveryIcon className="h-4 w-4" /> : <CollectIcon className="h-4 w-4" />}
          {delivery ? "Delivery from " : "Click & Collect at "}{detail.fulfilling_store_name}
          <span aria-hidden="true">·</span> placed {formatDateTime(detail.placed_at)}</span>}
        actions={<StatusBadge status={detail.status} />}
      />
      <NoticeBanner notice={notice} onClose={clear} />

      <Card className="mb-5">
        <div className="grid gap-6 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-center">
          <FulfilmentPath method={detail.fulfilment_method} status={detail.status}
            reached={detail.history.map((change) => change.to_status)} />
          <div className="space-y-3 lg:border-l lg:border-line lg:pl-6">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-muted">
              Next step <RuleTag>BR09</RuleTag>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {moves.map((to) => (
                <Button key={to} tone="primary" disabled={busy} onClick={() => move(detail, to)}>{MOVES[to]}</Button>
              ))}
              {canCancel && !confirmCancel && (
                <Button tone="ghost" disabled={busy} onClick={() => setConfirmCancel(true)}>Cancel order…</Button>
              )}
              {moves.length === 0 && !canCancel && (
                <p className="text-[15px] text-muted">
                  Nothing more to do: this order is {ORDER_STATUS_TEXT[detail.status].toLowerCase()}.
                </p>
              )}
            </div>
            {canCancel && confirmCancel && (
              <div className="space-y-3 rounded-tile border border-red-200 bg-red-50 p-4 text-sm text-red-900">
                <p>Put the items back in stock and refund {money(detail.payment.balance)}?</p>
                <div className="flex flex-wrap gap-2">
                  <Button tone="danger" disabled={busy} onClick={() => cancel(detail)}>Yes, cancel it</Button>
                  <Button disabled={busy} onClick={() => setConfirmCancel(false)}>Keep it</Button>
                </div>
              </div>
            )}
            <p className="text-xs text-muted">The transition table decides which moves are allowed.</p>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card title={<>Items to pick <span className="font-sans font-normal text-muted">· {units} {units === 1 ? "unit" : "units"}</span></>}>
          <Table label={`Items in order #${detail.order_id}`}
            columns={[{ label: "Qty", align: "right" }, "Product", { label: "Total", align: "right" }]}>
            {detail.lines.map((line) => (
              <Row key={line.line_no}>
                <Cell numeric className="w-16 font-display text-lg font-bold">× {line.quantity}</Cell>
                <Cell>
                  <div className="font-semibold">{line.name}</div>
                  <div className="font-mono text-xs text-muted">{line.sku}</div>
                </Cell>
                <Cell numeric>{money(line.line_total)}</Cell>
              </Row>
            ))}
          </Table>
          {detail.delivery_address && (
            <div className="flex items-start gap-2 border-t border-line px-5 py-4 text-sm">
              <DeliveryIcon className="mt-0.5 h-4 w-4 text-muted" />
              <span>
                <span className="block text-xs font-semibold uppercase tracking-[0.08em] text-muted">Ship to</span>
                {detail.delivery_address.line1}, {detail.delivery_address.suburb} {detail.delivery_address.state}{" "}
                {detail.delivery_address.postcode}
              </span>
            </div>
          )}
        </Card>

        <div className="space-y-5">
          <Card title="Timeline" actions={<RuleTag>R11</RuleTag>}>
            <OrderTimeline history={detail.history} />
          </Card>
          <Card title="Payment (simulated)"
            actions={<span className="flex gap-1"><RuleTag>BR14</RuleTag><RuleTag>BR20</RuleTag><RuleTag>BR21</RuleTag></span>}>
            <dl className="divide-y divide-line text-sm">
              {([["Charged", detail.payment.charged], ["Refunded", detail.payment.refunded],
                ["Held (charged − refunded)", detail.payment.balance]] as const).map(([label, value], index) => (
                <div key={label} className="flex items-center justify-between gap-4 px-5 py-3">
                  <dt className="text-muted">{label}</dt>
                  <dd className={`tabular-nums ${index === 2 ? "font-display text-base font-bold" : ""}`}>{money(value)}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      </div>
    </>
  );
}

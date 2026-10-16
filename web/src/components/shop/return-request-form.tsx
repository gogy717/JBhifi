"use client";

import Link from "next/link";
import { useState } from "react";

import { ReturnStatusBadge } from "@/components/return-status";
import { Button, Card, ErrorBox, Field, inputClass } from "@/components/ui";
import { api, type ApiError, call, type Me, type OrderDetail, type ReturnSummary, toApiError } from "@/lib/api/client";
import { fromCents, lineTotalCents } from "@/lib/cart";
import { formatDate, money } from "@/lib/format";
import { attemptFor, type ReturnAttempt, returnable, returnDeadline } from "@/lib/return-attempt";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

/** Ask to return items of a delivered or collected order (R6). Only the order's own customer sees it. Every limit
 *  shown here is checked again by the database: the 30-day window (BR11) and what is left to return (BR12). */
export function ReturnRequestForm({ order, me }: { order: OrderDetail; me: Me }) {
  if (me.kind !== "customer" || me.id !== order.customer_id) return null;
  const deadline = returnDeadline(order.status, order.history);
  if (!deadline) return null;
  return <RequestForm key={order.order_id} order={order} customerId={me.id} deadline={deadline} />;
}

function RequestForm({ order, customerId, deadline }: { order: OrderDetail; customerId: number; deadline: Date }) {
  const [now] = useState(() => Date.now());
  const returns = useLoad(`returns:${customerId}`, () =>
    call(api.GET("/api/v1/customers/{customer_id}/returns", { params: { path: { customer_id: customerId } } })));
  const [quantities, setQuantities] = useState<Record<number, number>>({});
  const [reason, setReason] = useState("");
  const [attempt, setAttempt] = useState<ReturnAttempt>();
  const [sending, setSending] = useState(false);
  const [unanswered, setUnanswered] = useState(false);
  const [error, setError] = useState<ApiError>();
  const [asked, setAsked] = useState<ReturnSummary>();

  const ofThisOrder = (returns.data ?? []).filter((row) => row.order_id === order.order_id);
  const left = returnable(order.lines, ofThisOrder, order.order_id);
  const chosen = order.lines
    .map((line) => ({ line_no: line.line_no, quantity: Math.min(quantities[line.line_no] ?? 0, left.get(line.line_no) ?? 0) }))
    .filter((line) => line.quantity > 0);
  const valueCents = chosen.reduce((sum, line) =>
    sum + lineTotalCents(order.lines.find((bought) => bought.line_no === line.line_no)?.unit_price ?? "0", line.quantity), 0);
  const open = deadline.getTime() > now;
  const anythingLeft = [...left.values()].some((quantity) => quantity > 0);

  async function send() {
    const body = { reason: reason.trim(), lines: chosen };
    // The same request after an unanswered try keeps its key, so it can't become a second return (BR10).
    const next = attemptFor(attempt, order.order_id, body);
    setAttempt(next);
    setSending(true);
    setError(undefined);
    try {
      const created = await call(api.POST("/api/v1/orders/{order_id}/returns", {
        params: { path: { order_id: order.order_id }, header: { "Idempotency-Key": next.key } },
        body,
      }));
      // 201 a new return, 200 the one this key asked for earlier: either way it exists now.
      setAsked(created);
      setAttempt(undefined);
      setUnanswered(false);
      setQuantities({});
      setReason("");
      returns.reload();
    } catch (caught) {
      const failure = toApiError(caught);
      setError(failure);
      // No answer, or no clear one: the request may have gone through. Keep it exactly as sent, so "Try again"
      // repeats it with its key. A clear refusal saved nothing, so the next request is a new one.
      const unknown = failure.status === 0 || failure.status >= 500;
      setUnanswered(unknown);
      if (!unknown) setAttempt(undefined);
    } finally {
      setSending(false);
    }
  }

  return (
    <Card title="Return items" actions={<span className="text-xs text-neutral-500">R6 · BR11 · BR12</span>}>
      <div className="space-y-4 px-4 py-3 text-sm">
        {asked && (
          <p role="status" className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-800 ring-1 ring-emerald-200">
            Return #{asked.return_id} requested. Bring the items to any JB Hi-Fi store; you&apos;re refunded{" "}
            {money(asked.value)} once they are checked. Follow it on{" "}
            <Link href={SHOP_PAGES.returns.href} className="font-medium underline">My returns</Link>.
          </p>
        )}
        {ofThisOrder.length > 0 && (
          <ul className="divide-y divide-neutral-100 rounded-lg ring-1 ring-neutral-200">
            {ofThisOrder.map((row) => (
              <li key={row.return_id} className="flex items-center justify-between gap-3 px-3 py-2">
                <span>Return #{row.return_id} · {row.quantity} {row.quantity === 1 ? "item" : "items"} · {money(row.value)}</span>
                <ReturnStatusBadge status={row.status} />
              </li>
            ))}
          </ul>
        )}
        {returns.error && (
          <div className="flex flex-wrap items-center gap-3">
            <ErrorBox error={returns.error} />
            <Button onClick={returns.reload}>Try again</Button>
          </div>
        )}

        {!open ? (
          <p className="text-neutral-600">The 30-day return window closed on {formatDate(deadline.toISOString())}.</p>
        ) : !returns.data ? (
          !returns.error && <div className="h-16 animate-pulse rounded bg-neutral-100" />
        ) : !anythingLeft ? (
          <p className="text-neutral-600">Every item of this order has been asked for already.</p>
        ) : (
          <>
            <p className="text-neutral-600">
              Returns are accepted until {formatDate(deadline.toISOString())}, at the price you paid.
            </p>
            <ul className="space-y-2">
              {order.lines.map((line) => {
                const most = left.get(line.line_no) ?? 0;
                return (
                  <li key={line.line_no} className="flex flex-wrap items-center justify-between gap-3">
                    <span>
                      <span className="font-medium">{line.name}</span>
                      <span className="block text-xs text-neutral-500">
                        {money(line.unit_price)} each · {most} of {line.quantity} left to return
                      </span>
                    </span>
                    <input type="number" min={0} max={most} step={1} aria-label={`How many ${line.name} to return`}
                      className={`${inputClass} w-20`} disabled={most === 0 || sending || unanswered}
                      value={Math.min(quantities[line.line_no] ?? 0, most)}
                      onChange={(event) => {
                        const typed = Math.trunc(Number(event.target.value));
                        setQuantities({ ...quantities, [line.line_no]: Number.isFinite(typed) ? Math.max(0, Math.min(typed, most)) : 0 });
                      }} />
                  </li>
                );
              })}
            </ul>
            <Field label="Why are you returning them?">
              <textarea className={`${inputClass} h-20 py-2`} maxLength={500} value={reason}
                disabled={sending || unanswered} onChange={(event) => setReason(event.target.value)} />
            </Field>
            {error && <ErrorBox error={error} onClose={unanswered ? undefined : () => setError(undefined)} />}
            {unanswered && (
              <p className="text-amber-800">
                We couldn&apos;t confirm the request. Try again: it is sent exactly as before, so it can&apos;t be
                asked for twice.
              </p>
            )}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="text-neutral-600">
                Refund on approval: <b className="tabular-nums">{money(fromCents(valueCents))}</b>
              </span>
              <Button tone="primary" onClick={send} disabled={sending || chosen.length === 0 || reason.trim() === ""}>
                {sending ? "Sending…" : unanswered ? "Try again" : "Request return"}
              </Button>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

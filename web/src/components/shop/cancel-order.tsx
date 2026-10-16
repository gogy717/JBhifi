"use client";

import { useState } from "react";

import { Button, ErrorBox } from "@/components/ui";
import { type ApiError, api, call, type Me, type OrderDetail, type OrderStatus, toApiError } from "@/lib/api/client";
import { money } from "@/lib/format";

/** The customer's "Cancel order" (T4), shown while the store hasn't started on it (paid). Cancelling puts the
 *  items back in stock and refunds what was charged, in one transaction; the API decides, this only asks. */
export function CancelOrder({ order, me, onDone }: { order: OrderDetail; me: Me; onDone: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError>();

  const offered = me.kind === "customer" && order.customer_id === me.id && order.status === "paid";
  // A refusal stays on screen after the reload that hides the button, so the customer sees why it failed.
  if (!offered && !error) return null;

  async function cancel() {
    setBusy(true);
    setError(undefined);
    try {
      await call(api.POST("/api/v1/orders/{order_id}/cancel", {
        params: { path: { order_id: order.order_id } },
        body: { from_status: order.status as OrderStatus },
      }));
      onDone();
    } catch (failure) {
      const apiError = toApiError(failure);
      // The store started on it in the meantime: show the order as it is now, with the reason.
      if (apiError.code === "status_changed") onDone();
      setError(apiError);
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <div className="mt-3 space-y-2">
      {offered && !confirming && (
        <Button size="sm" disabled={busy} onClick={() => setConfirming(true)}>Cancel order…</Button>
      )}
      {offered && confirming && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>Cancel this order? You&apos;ll be refunded {money(order.payment.balance)}.</span>
          <Button size="sm" tone="danger" disabled={busy} onClick={cancel}>Yes, cancel it</Button>
          <Button size="sm" disabled={busy} onClick={() => setConfirming(false)}>Keep it</Button>
        </div>
      )}
      {error && <ErrorBox error={error} onClose={() => setError(undefined)} />}
    </div>
  );
}

"use client";

import { useState } from "react";

import { Button, ErrorBox, Field, inputClass, Modal } from "@/components/ui";
import { ORDER_STATUS_TEXT } from "@/components/shop/order-timeline";
import { ApiError, api, call, type OrderDetail, type OrderStatus } from "@/lib/api/client";
import { money } from "@/lib/format";

/** The buttons come from the server's `allowed_actions`, so the page keeps no transition table of its own. */
export function OrderActions({ order, onChanged }: {
  order: OrderDetail;
  onChanged: (updated: OrderDetail) => void;
}) {
  const [error, setError] = useState<ApiError>();
  const [pending, setPending] = useState<string>();
  const [cancelling, setCancelling] = useState(false);

  async function move(to_status: string) {
    setPending(to_status);
    setError(undefined);
    try {
      const updated = await call(api.PATCH("/api/v1/orders/{order_id}/status", {
        params: { path: { order_id: order.order_id } },
        // The status the screen is showing: if it is stale the server says so instead of guessing.
        body: { to_status: to_status as OrderStatus, expected_status: order.status },
      }));
      onChanged(updated);
    } catch (failure) {
      setError(failure instanceof ApiError ? failure
        : new ApiError(0, "network_error", "The request did not get an answer."));
      if (failure instanceof ApiError && failure.code === "stale_status") onChanged(order);
    } finally {
      setPending(undefined);
    }
  }

  const moves = order.allowed_actions.filter((action) => action !== "cancel");
  const canCancel = order.allowed_actions.includes("cancel");

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {moves.length === 0 && !canCancel && (
          <p className="text-sm text-neutral-500">
            Nothing to do: this order is {ORDER_STATUS_TEXT[order.status]?.toLowerCase() ?? order.status}.
          </p>
        )}
        {moves.map((action) => (
          <Button key={action} tone="primary" disabled={pending !== undefined} onClick={() => move(action)}>
            {pending === action ? "Saving…" : `Mark ${ORDER_STATUS_TEXT[action] ?? action}`}
          </Button>
        ))}
        {canCancel && (
          <Button tone="danger" disabled={pending !== undefined} onClick={() => setCancelling(true)}>
            Cancel order…
          </Button>
        )}
      </div>
      {error && <ErrorBox error={error} />}
      {error?.code === "stale_status" && (
        <p className="text-xs text-neutral-600">
          Someone else moved this order first. The page now shows where it actually is — look before acting.
        </p>
      )}
      {cancelling && (
        <CancelDialog order={order} onClose={() => setCancelling(false)}
          onCancelled={(updated) => { setCancelling(false); onChanged(updated); }}
          onError={setError} />
      )}
    </div>
  );
}

function CancelDialog({ order, onClose, onCancelled, onError }: {
  order: OrderDetail;
  onClose: () => void;
  onCancelled: (updated: OrderDetail) => void;
  onError: (error: ApiError) => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<ApiError>();
  const [pending, setPending] = useState(false);
  const captured = order.payments.filter((payment) => payment.kind === "charge")
    .reduce((total, payment) => total + Number(payment.amount), 0);

  async function submit() {
    setPending(true);
    setError(undefined);
    try {
      const updated = await call(api.POST("/api/v1/orders/{order_id}/cancel", {
        params: { path: { order_id: order.order_id } },
        body: { expected_status: order.status, reason: reason.trim() },
      }));
      onCancelled(updated);
    } catch (failure) {
      const apiError = failure instanceof ApiError ? failure
        : new ApiError(0, "network_error", "The request did not get an answer.");
      setError(apiError);
      onError(apiError);
    } finally {
      setPending(false);
    }
  }

  return (
    <Modal title={`Cancel order #${order.order_id}`} onClose={onClose} footer={<>
      <Button onClick={onClose}>Keep the order</Button>
      <Button tone="danger" disabled={pending || reason.trim().length === 0} onClick={submit}>
        {pending ? "Cancelling…" : "Cancel and refund"}
      </Button>
    </>}>
      <p className="text-sm text-neutral-700">
        This is one transaction: the stock goes back to{" "}
        <b>{order.fulfilling_store_name}</b>, {money(String(captured))} is refunded against a cancellation
        record, and the order becomes cancelled.
      </p>
      <ul className="rounded-lg bg-neutral-50 px-4 py-3 text-sm">
        {order.lines.map((line) => (
          <li key={line.line_no} className="flex justify-between gap-3">
            <span>{line.quantity} × {line.name}</span>
            <span className="tabular-nums text-neutral-600">back to stock</span>
          </li>
        ))}
      </ul>
      <Field label="Why is it being cancelled?">
        <input className={inputClass} value={reason} maxLength={500}
          placeholder="e.g. customer changed their mind, no stock after all"
          onChange={(event) => setReason(event.target.value)} />
      </Field>
      {error && <ErrorBox error={error} />}
    </Modal>
  );
}

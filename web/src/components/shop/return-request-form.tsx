"use client";

import { useState } from "react";

import { Button, ErrorBox, inputClass } from "@/components/ui";
import { ApiError, api, call, type OrderDetail, type ReturnDetail } from "@/lib/api/client";
import { newAttemptKey } from "@/lib/checkout-attempt";
import { money } from "@/lib/format";

/** The attempt key for one reviewed return, kept across an uncertain outcome exactly like checkout's. */
const RETURN_ATTEMPT_KEY = "jb.shop.returnAttempt";

/** The key for one reviewed return, kept so an uncertain outcome can be retried without a second request. */
function attemptKey(body: string): string {
  try {
    const raw = window.sessionStorage.getItem(RETURN_ATTEMPT_KEY);
    const stored = raw ? JSON.parse(raw) as { key: string; body: string } : undefined;
    if (stored?.body === body) return stored.key;
  } catch {
    // fall through and mint a new key
  }
  const key = newAttemptKey();
  try {
    window.sessionStorage.setItem(RETURN_ATTEMPT_KEY, JSON.stringify({ key, body }));
  } catch {
    // the request still works; a reload simply creates a new key
  }
  return key;
}

export function ReturnRequestForm({ order, onRequested }: {
  order: OrderDetail;
  onRequested: (detail: ReturnDetail) => void;
}) {
  const eligibility = order.return_eligibility;
  const returnable = eligibility.lines.filter((line) => line.remaining_quantity > 0);
  const [quantities, setQuantities] = useState<Record<number, number>>({});
  const [reason, setReason] = useState("");
  const [error, setError] = useState<ApiError>();
  const [pending, setPending] = useState(false);

  const lines = returnable
    .map((line) => ({ line_no: line.line_no, quantity: quantities[line.line_no] ?? 0, line }))
    .filter((entry) => entry.quantity > 0);
  const preview = lines.reduce((total, entry) => total + Number(entry.line.unit_price) * entry.quantity, 0);
  const ready = lines.length > 0 && reason.trim().length > 0;

  async function submit() {
    setPending(true);
    setError(undefined);
    const body = {
      reason: reason.trim(),
      lines: lines.map((entry) => ({ line_no: entry.line_no, quantity: entry.quantity })),
    };
    const key = attemptKey(JSON.stringify(body));
    try {
      const detail = await call(api.POST("/api/v1/orders/{order_id}/returns", {
        params: { path: { order_id: order.order_id }, header: { "Idempotency-Key": key } },
        body,
      }));
      try {
        window.sessionStorage.removeItem(RETURN_ATTEMPT_KEY);
      } catch {
        // nothing to clear
      }
      onRequested(detail);
    } catch (failure) {
      setError(failure instanceof ApiError ? failure
        : new ApiError(0, "network_error", "The request did not get an answer. Try again — it is safe."));
    } finally {
      setPending(false);
    }
  }

  if (!eligibility.eligible) {
    return (
      <div className="px-4 py-4 text-sm">
        <p className="text-neutral-600">{eligibility.reason}</p>
        {eligibility.deadline && (
          <p className="mt-1 text-xs text-neutral-500">
            The window ran to {new Date(eligibility.deadline).toLocaleDateString("en-AU")}.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3 p-4">
      <p className="text-xs text-neutral-500">
        Return window open until{" "}
        {eligibility.deadline ? new Date(eligibility.deadline).toLocaleDateString("en-AU") : "—"}. Refunds use
        the price you paid, and stock is only put back once the store has the item.
      </p>
      <ul className="divide-y divide-neutral-100 rounded-lg border border-neutral-200">
        {returnable.map((line) => (
          <li key={line.line_no} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5 text-sm">
            <span>
              <span className="font-medium">{line.name}</span>
              <span className="block text-xs text-neutral-500">
                {money(line.unit_price)} each · bought {line.quantity}
                {line.returned_quantity > 0 && ` · ${line.returned_quantity} already returned`}
                {" · "}{line.remaining_quantity} left
              </span>
            </span>
            <label className="flex items-center gap-2 text-xs text-neutral-600">
              Return
              <input className={`${inputClass} w-20`} type="number" min={0} max={line.remaining_quantity} step={1}
                value={quantities[line.line_no] ?? 0}
                aria-label={`Quantity to return of ${line.name}`}
                onChange={(event) => setQuantities((current) => ({
                  ...current,
                  [line.line_no]: Math.max(0, Math.min(line.remaining_quantity,
                    Math.trunc(Number(event.target.value) || 0))),
                }))} />
            </label>
          </li>
        ))}
      </ul>
      <label className="block">
        <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-500">
          Why are you returning it? (required)
        </span>
        <input className={inputClass} value={reason} maxLength={500}
          placeholder="e.g. changed my mind, wrong size"
          onChange={(event) => setReason(event.target.value)} />
      </label>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-neutral-600">
          Refund if accepted: <b>{money(String(preview))}</b>
        </p>
        <Button tone="primary" disabled={!ready || pending} onClick={submit}>
          {pending ? "Requesting…" : "Request return"}
        </Button>
      </div>
      {error && <ErrorBox error={error} />}
      {error?.code === "idempotency_conflict" && (
        <p className="text-xs text-neutral-600">
          That request was already sent with different details. Change them back, or reload the page.
        </p>
      )}
    </div>
  );
}

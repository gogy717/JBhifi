"use client";

import { useState } from "react";

import { Button, ErrorBox, Modal } from "@/components/ui";
import { RETURN_STATUS_TEXT } from "@/components/shop/order-timeline";
import { ApiError, api, call, type ReturnDetail } from "@/lib/api/client";
import { money } from "@/lib/format";

const ACTION_TEXT: Record<string, string> = {
  receive: "Receive it",
  reject: "Reject the return",
  process: "Process the refund",
};

/** Receive / reject / process — only the ones the server says this store may do, in this state. */
export function ReturnActions({ detail, onChanged }: {
  detail: ReturnDetail;
  onChanged: (updated: ReturnDetail) => void;
}) {
  const [error, setError] = useState<ApiError>();
  const [pending, setPending] = useState<string>();
  const [confirming, setConfirming] = useState<string>();

  async function act(action: string) {
    setPending(action);
    setError(undefined);
    try {
      // Each action has its own endpoint, so a status PATCH can never impersonate one of them.
      const options = {
        params: { path: { return_id: detail.return_id } },
        // The status the screen is showing; a stale one is reported rather than silently applied.
        body: { expected_status: detail.status },
      };
      const updated = await call(
        action === "receive" ? api.POST("/api/v1/returns/{return_id}/receive", options)
          : action === "reject" ? api.POST("/api/v1/returns/{return_id}/reject", options)
            : api.POST("/api/v1/returns/{return_id}/process", options));
      onChanged(updated);
      setConfirming(undefined);
    } catch (failure) {
      setError(failure instanceof ApiError ? failure
        : new ApiError(0, "network_error", "The request did not get an answer. Try the same action again."));
      if (failure instanceof ApiError && failure.code === "stale_status") onChanged(detail);
    } finally {
      setPending(undefined);
    }
  }

  const actions = detail.allowed_actions;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {actions.length === 0 && (
          <p className="text-sm text-neutral-500">
            Nothing for this store to do: the return is{" "}
            {RETURN_STATUS_TEXT[detail.status]?.toLowerCase() ?? detail.status}.
          </p>
        )}
        {actions.map((action) => (
          <Button key={action} tone={action === "reject" ? "danger" : action === "process" ? "primary" : "secondary"}
            disabled={pending !== undefined}
            onClick={() => action === "receive" ? act(action) : setConfirming(action)}>
            {pending === action ? "Saving…" : ACTION_TEXT[action] ?? action}
          </Button>
        ))}
      </div>
      {error && <ErrorBox error={error} />}
      {error?.code === "stale_status" && (
        <p className="text-xs text-neutral-600">
          This return moved on while you were looking at it. The page now shows where it is.
        </p>
      )}
      {confirming && (
        <ConfirmDialog action={confirming} detail={detail} pending={pending === confirming}
          onClose={() => setConfirming(undefined)} onConfirm={() => act(confirming)} />
      )}
    </div>
  );
}

function ConfirmDialog({ action, detail, pending, onClose, onConfirm }: {
  action: string;
  detail: ReturnDetail;
  pending: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <Modal title={ACTION_TEXT[action] ?? action} onClose={onClose} footer={<>
      <Button onClick={onClose}>Back</Button>
      <Button tone={action === "reject" ? "danger" : "primary"} disabled={pending} onClick={onConfirm}>
        {pending ? "Saving…" : ACTION_TEXT[action] ?? action}
      </Button>
    </>}>
      {action === "process" ? (
        <>
          <p className="text-sm text-neutral-700">
            This restocks the returned quantities at{" "}
            <b>{detail.receiving_store?.name ?? "this store"}</b> and refunds{" "}
            <b>{money(String(detail.refund_preview))}</b> — the prices they were bought at, not today&apos;s
            prices.
          </p>
          <ul className="rounded-lg bg-neutral-50 px-4 py-3 text-sm">
            {detail.lines.map((line) => (
              <li key={line.line_no} className="flex justify-between gap-3">
                <span>{line.quantity} × {line.name}</span>
                <span className="tabular-nums text-neutral-600">{money(line.line_total)}</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-sm text-neutral-700">
          Rejecting is final and refunds nothing, because the stock was never put back. The customer still
          sees the request and the reason on their returns page.
        </p>
      )}
    </Modal>
  );
}

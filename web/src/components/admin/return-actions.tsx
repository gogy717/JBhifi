"use client";

import { useState } from "react";

import { Button, ErrorBox, Field, inputClass, Modal } from "@/components/ui";
import { api, type ApiError, call, type Me, type ReturnDetail, toApiError } from "@/lib/api/client";
import { money } from "@/lib/format";

type Action = "receive" | "refund" | "reject";

/** The buttons a store's staff member has for a return: receive a requested return at their store; refund or
 *  reject one their store received. Support staff read returns but don't act on them. The API checks all of it
 *  again under its locks: whoever is second gets 409 return_status_transition, and the page reloads. */
export function ReturnActions({ detail, me, onChanged, onStale }: {
  detail: ReturnDetail;
  me: Me;
  onChanged: (detail: ReturnDetail) => void;
  onStale: () => void;
}) {
  const [dialog, setDialog] = useState<"refund" | "reject">();
  const [reason, setReason] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<ApiError>();

  if (me.staff_type !== "store") {
    return <p className="text-sm text-neutral-500">Support staff can read returns; a store&apos;s staff handle them.</p>;
  }
  const ours = detail.received_store_id === me.store_id;
  const canReceive = detail.status === "requested";
  const canResolve = detail.status === "received" && ours;
  // Kept above the "nothing to do" branch: after a refused click the page reloads, often into a final return,
  // and the person who came second still needs to read why their click did nothing.
  const errorBox = error && <ErrorBox error={error} onClose={() => setError(undefined)} />;
  if (!canReceive && !canResolve) {
    return (
      <div className="space-y-3">
        {errorBox}
        <p className="text-sm text-neutral-500">
          {detail.status === "received" ? `Received at ${detail.received_store_name}: that store finishes it.`
            : "Nothing left to do: this return is final."}
        </p>
      </div>
    );
  }

  async function act(action: Action) {
    setSending(true);
    setError(undefined);
    const path = { params: { path: { return_id: detail.return_id } } };
    try {
      const changed = await call(
        action === "receive" ? api.POST("/api/v1/returns/{return_id}/receive", path)
          : action === "refund" ? api.POST("/api/v1/returns/{return_id}/refund", path)
          : api.POST("/api/v1/returns/{return_id}/reject", { ...path, body: { reason: reason.trim() } }));
      setDialog(undefined);
      setReason("");
      onChanged(changed);
    } catch (caught) {
      const failure = toApiError(caught);
      setError(failure);
      setDialog(undefined);
      // Someone else got there first: another click moved it on (409), or another store received it (403).
      if (failure.code === "return_status_transition" || failure.code === "other_store") onStale();
    } finally {
      setSending(false);
    }
  }

  const items = detail.lines.reduce((sum, line) => sum + line.quantity, 0);
  return (
    <div className="space-y-3">
      {errorBox}
      <div className="flex flex-wrap gap-2">
        {canReceive && (
          <Button tone="primary" disabled={sending} onClick={() => act("receive")}>
            {sending ? "Receiving…" : `Receive at ${me.store_name}`}
          </Button>
        )}
        {canResolve && (
          <>
            <Button tone="primary" disabled={sending} onClick={() => setDialog("refund")}>Refund {money(detail.value)}…</Button>
            <Button tone="danger" disabled={sending} onClick={() => setDialog("reject")}>Reject…</Button>
          </>
        )}
      </div>
      {canReceive && (
        <p className="text-xs text-neutral-500">
          Receiving records your store and you. Nothing is restocked or refunded until you check the items.
        </p>
      )}

      {dialog === "refund" && (
        <Modal title={`Refund return #${detail.return_id}`} onClose={() => setDialog(undefined)}
          footer={<>
            <Button onClick={() => setDialog(undefined)}>Cancel</Button>
            <Button tone="primary" disabled={sending} onClick={() => act("refund")}>
              {sending ? "Refunding…" : `Restock and refund ${money(detail.value)}`}
            </Button>
          </>}>
          <p className="text-sm text-neutral-700">
            One transaction (T2): {items} {items === 1 ? "item goes" : "items go"} back into {me.store_name}&apos;s
            stock, {Number(detail.value) > 0 ? <>{money(detail.value)} is refunded</> : "nothing is owed back"}, and the
            return is marked refunded — all of it, or none of it.
          </p>
          <ul className="space-y-0.5 text-sm">
            {detail.lines.map((line) => (
              <li key={line.line_no}>{line.quantity} × {line.name} at {money(line.unit_price)}</li>
            ))}
          </ul>
        </Modal>
      )}

      {dialog === "reject" && (
        <Modal title={`Reject return #${detail.return_id}`} onClose={() => setDialog(undefined)}
          footer={<>
            <Button onClick={() => setDialog(undefined)}>Cancel</Button>
            <Button tone="danger" disabled={sending || reason.trim() === ""} onClick={() => act("reject")}>
              {sending ? "Rejecting…" : "Reject"}
            </Button>
          </>}>
          <Field label="Reason" hint="The customer sees it. Nothing is restocked or refunded; rejected is final.">
            <textarea className={`${inputClass} h-20 py-2`} maxLength={500} value={reason}
              onChange={(event) => setReason(event.target.value)} />
          </Field>
        </Modal>
      )}
    </div>
  );
}

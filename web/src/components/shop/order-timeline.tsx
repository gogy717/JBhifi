import { Badge } from "@/components/ui";
import type { OrderDetail } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";

type HistoryEntry = OrderDetail["history"][number];

/** Plain-language names for the database's order statuses, so staff and customers see the same words. */
export const ORDER_STATUS_TEXT: Record<string, string> = {
  placed: "Placed",
  paid: "Paid",
  picking: "Being picked",
  shipped: "Shipped",
  delivered: "Delivered",
  ready: "Ready to collect",
  collected: "Collected",
  cancelled: "Cancelled",
};

const TONES: Record<string, "neutral" | "blue" | "amber" | "green" | "sale" | "red"> = {
  placed: "neutral", paid: "blue", picking: "amber", shipped: "blue", delivered: "green",
  ready: "sale", collected: "green", cancelled: "red",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={TONES[status] ?? "neutral"}>{ORDER_STATUS_TEXT[status] ?? status}</Badge>;
}

/** Every recorded status change, oldest first, with when and who made it (R11). Ordered by seq, never by time:
 *  checkout writes `placed` and `paid` in one transaction, so both rows have the same timestamp. Drawn as a rail
 *  of dots; the newest change, where the order is now, has the brand dot. */
export function OrderTimeline({ history }: { history: HistoryEntry[] }) {
  const changes = [...history].sort((a, b) => a.seq - b.seq);
  return (
    <ol className="px-5 py-4">
      {changes.map((change, index) => {
        const latest = index === changes.length - 1;
        return (
          <li key={change.seq} aria-current={latest ? "step" : undefined} className="flex gap-3.5">
            <span aria-hidden="true" className="flex w-3 shrink-0 flex-col items-center">
              <span className={`mt-1.5 h-3 w-3 shrink-0 rounded-full ${latest
                ? "bg-brand ring-4 ring-brand-soft" : "border-2 border-faint bg-white"}`} />
              {!latest && <span className="my-1 w-0.5 flex-1 rounded-full bg-line" />}
            </span>
            <div className={`min-w-0 flex-1 ${latest ? "" : "pb-5"}`}>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <StatusBadge status={change.to_status} />
                <span className="text-[13px] text-muted">
                  {change.from_status
                    ? `from ${ORDER_STATUS_TEXT[change.from_status] ?? change.from_status}`
                    : "order created"}
                </span>
              </div>
              <div className="mt-1 text-[13px] text-muted tabular-nums">
                {formatDateTime(change.changed_at)}
                {/* No staff member recorded: the customer made the change (at checkout, or cancelling). */}
                <span> · by {change.changed_by_name ?? "the customer"}</span>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

const either = new Intl.ListFormat("en-AU", { type: "disjunction" });

/** The moves the transition table allows from the current status (BR09), as text: on the storefront only the
 *  customer's cancel button (components/shop/cancel-order.tsx) changes a status. */
export function NextStatuses({ statuses }: { statuses: string[] }) {
  const names = statuses.map((status) => (ORDER_STATUS_TEXT[status] ?? status).toLowerCase());
  return (
    <p className="text-[15px] text-muted">
      {names.length === 0 ? "Nothing more happens to this order." : `What happens next: ${either.format(names)}.`}
    </p>
  );
}

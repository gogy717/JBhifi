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
 *  checkout writes `placed` and `paid` in one transaction, so both rows have the same timestamp. */
export function OrderTimeline({ history }: { history: HistoryEntry[] }) {
  const changes = [...history].sort((a, b) => a.seq - b.seq);
  return (
    <ol className="divide-y divide-neutral-100">
      {changes.map((change) => (
        <li key={change.seq} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
          <span className="w-30 shrink-0 text-xs tabular-nums text-neutral-500">
            {formatDateTime(change.changed_at)}
          </span>
          <StatusBadge status={change.to_status} />
          <span className="text-neutral-600">
            {change.from_status ? `from ${ORDER_STATUS_TEXT[change.from_status] ?? change.from_status}` : "order created"}
            {/* No staff member recorded: the customer made the change (at checkout, or cancelling). */}
            <span className="text-neutral-500"> · by {change.changed_by_name ?? "the customer"}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

const either = new Intl.ListFormat("en-AU", { type: "disjunction" });

/** The moves the transition table allows from the current status (BR09), as text: on the storefront only the
 *  customer's cancel button (components/shop/cancel-order.tsx) changes a status. */
export function NextStatuses({ statuses }: { statuses: string[] }) {
  const names = statuses.map((status) => (ORDER_STATUS_TEXT[status] ?? status).toLowerCase());
  return (
    <p className="text-sm text-neutral-600">
      {names.length === 0 ? "Nothing more happens to this order." : `What happens next: ${either.format(names)}.`}
    </p>
  );
}

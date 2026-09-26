import { Badge } from "@/components/ui";
import type { OrderStatus, ReturnStatus, StatusHistoryEntry } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";

/** Plain-language names for the database's statuses, so staff and customers see the same words. */
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

export const RETURN_STATUS_TEXT: Record<string, string> = {
  requested: "Requested",
  received: "Received by the store",
  refunded: "Refunded",
  rejected: "Rejected",
};

const TONES: Record<string, "neutral" | "blue" | "amber" | "green" | "sale" | "red"> = {
  placed: "neutral", paid: "blue", picking: "amber", shipped: "blue", delivered: "green",
  ready: "sale", collected: "green", cancelled: "red",
  requested: "amber", received: "blue", refunded: "green", rejected: "red",
} as const;

export function StatusBadge({ status }: { status: OrderStatus | ReturnStatus | string }) {
  const tone = TONES[status] ?? "neutral";
  return <Badge tone={tone}>{ORDER_STATUS_TEXT[status] ?? RETURN_STATUS_TEXT[status] ?? status}</Badge>;
}

/** Every recorded status change, oldest first, with when and who made it (R11). */
export function OrderTimeline({ history }: { history: StatusHistoryEntry[] }) {
  return (
    <ol className="divide-y divide-neutral-100">
      {history.map((change) => (
        <li key={change.seq} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
          <span className="w-30 shrink-0 text-xs tabular-nums text-neutral-500">
            {formatDateTime(change.changed_at)}
          </span>
          <StatusBadge status={change.to_status} />
          <span className="text-neutral-600">
            {change.from_status ? `from ${ORDER_STATUS_TEXT[change.from_status] ?? change.from_status}` : "order created"}
            {change.changed_by_name
              ? <span className="text-neutral-500"> · by {change.changed_by_name}</span>
              : <span className="text-neutral-500"> · by the customer</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

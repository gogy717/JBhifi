import { Badge } from "@/components/ui";

/** Plain-language names for the return statuses (return_request_status_valid), shared by the shop and the admin. */
export const RETURN_STATUS_TEXT: Record<string, string> = {
  requested: "Requested",
  received: "Received",
  refunded: "Refunded",
  rejected: "Rejected",
};

const TONES: Record<string, "neutral" | "blue" | "amber" | "green" | "red"> = {
  requested: "amber", received: "blue", refunded: "green", rejected: "red",
};

export function ReturnStatusBadge({ status }: { status: string }) {
  return <Badge tone={TONES[status] ?? "neutral"}>{RETURN_STATUS_TEXT[status] ?? status}</Badge>;
}

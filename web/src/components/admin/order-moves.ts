import type { StaffMove } from "@/lib/api/client";

/** The forward moves staff make, in path order, with what the button says. */
export const MOVES: Record<StaffMove, string> = {
  picking: "Start picking",
  ready: "Ready for collection",
  shipped: "Mark shipped",
  collected: "Mark collected",
  delivered: "Mark delivered",
};

export function isMove(status: string): status is StaffMove {
  return status in MOVES;
}

/** The store's next move for an order in its queue, as the order page will offer it. Only a hint for the list:
 *  the order page asks the API, which reads the transition table (BR09). */
export function nextMove(status: string, method: string): StaffMove | undefined {
  switch (status) {
    case "paid": return "picking";
    case "picking": return method === "delivery" ? "shipped" : "ready";
    case "ready": return "collected";
    case "shipped": return "delivered";
    default: return undefined;
  }
}

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Me, OrderDetail } from "@/lib/api/client";

import { CancelOrder } from "./cancel-order";

const customer: Me = { kind: "customer", id: 7, display_name: "Alice", runs_store: false };
const staff: Me = { kind: "staff", id: 14, display_name: "Aiden", store_id: 1, staff_type: "store", runs_store: false };

function anOrder(status: string, customerId = 7): OrderDetail {
  return {
    order_id: 42, customer_id: customerId, placed_at: "2026-10-16T00:00:00Z", status,
    fulfilment_method: "click_collect", fulfilling_store_id: 1, fulfilling_store_name: "Sydney CBD",
    total: "200.00", line_count: 1, last_updated_at: "2026-10-16T00:00:00Z", lines: [], delivery_address: null,
    payment: { charged: "200.00", refunded: "0.00", balance: "200.00" }, history: [],
    allowed_next_statuses: status === "paid" ? ["picking", "cancelled"] : [],
  };
}

function button() {
  return screen.queryByRole("button", { name: "Cancel order…" });
}

describe("the customer's cancel button", () => {
  it("cancel_is_offered_on_the_customers_own_paid_order", () => {
    render(<CancelOrder order={anOrder("paid")} me={customer} onDone={() => {}} />);
    expect(button()).toBeInTheDocument();
  });

  it("cancel_is_not_offered_once_the_store_has_started", () => {
    for (const status of ["picking", "ready", "collected", "cancelled"]) {
      const { unmount } = render(<CancelOrder order={anOrder(status)} me={customer} onDone={() => {}} />);
      expect(button()).not.toBeInTheDocument();
      unmount();
    }
  });

  it("cancel_is_not_offered_to_staff_or_another_customer", () => {
    const { unmount } = render(<CancelOrder order={anOrder("paid")} me={staff} onDone={() => {}} />);
    expect(button()).not.toBeInTheDocument();
    unmount();
    render(<CancelOrder order={anOrder("paid", 8)} me={customer} onDone={() => {}} />);
    expect(button()).not.toBeInTheDocument();
  });
});

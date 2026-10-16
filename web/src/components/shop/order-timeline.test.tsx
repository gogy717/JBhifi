import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { OrderDetail } from "@/lib/api/client";

import { OrderTimeline } from "./order-timeline";

type Entry = OrderDetail["history"][number];
const at = "2026-10-16T01:00:00Z";
const entry = (seq: number, from: string | null, to: string, by: string | null = null): Entry => ({
  seq, from_status: from, to_status: to, changed_at: at, changed_by_staff_id: by ? 14 : null, changed_by_name: by,
});

describe("the order timeline", () => {
  it("lists_the_changes_by_seq_with_the_newest_as_the_current_step", () => {
    // placed and paid share a timestamp (one checkout transaction): only seq orders them. Given out of order here.
    render(<OrderTimeline history={[entry(3, "paid", "picking", "Aiden Chen"), entry(1, null, "placed"),
      entry(2, "placed", "paid")]} />);
    const steps = screen.getAllByRole("listitem");
    expect(steps.map((step) => within(step).getAllByText(/./)[0].textContent)).toEqual(["Placed", "Paid", "Being picked"]);
    expect(steps[2]).toHaveAttribute("aria-current", "step");
    expect(steps[0]).not.toHaveAttribute("aria-current");
  });

  it("says_who_made_each_change_and_the_customer_when_no_staff_member_did", () => {
    render(<OrderTimeline history={[entry(1, null, "placed"), entry(2, "placed", "paid", "Aiden Chen")]} />);
    const [created, paid] = screen.getAllByRole("listitem");
    expect(created).toHaveTextContent("order created");
    expect(created).toHaveTextContent("by the customer");
    expect(paid).toHaveTextContent("from Placed");
    expect(paid).toHaveTextContent("by Aiden Chen");
  });
});

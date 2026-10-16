import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Me, ReturnDetail } from "@/lib/api/client";

import { ReturnActions } from "./return-actions";

const aiden: Me = { kind: "staff", id: 14, display_name: "Aiden Chen", store_id: 1, store_name: "Sydney CBD",
  staff_type: "store", runs_store: false };
const isla: Me = { ...aiden, id: 16, display_name: "Isla Robinson", store_id: 2, store_name: "Bondi Junction" };
const nora: Me = { kind: "staff", id: 40, display_name: "Nora Fitzgerald", store_id: null, store_name: null,
  staff_type: "support", runs_store: false };

function aReturn(status: string, received_store_id: number | null = null): ReturnDetail {
  return {
    return_id: 7, order_id: 3, customer_id: 9, fulfilling_store_id: 1, status, reason: "Too big",
    requested_at: "2026-10-10T00:00:00Z", quantity: 1, value: "189.00", refunded: null,
    received_store_id, received_store_name: received_store_id === 1 ? "Sydney CBD" : null,
    received_at: received_store_id ? "2026-10-11T00:00:00Z" : null, resolved_at: null, rejection_reason: null,
    processed_by_name: null, resolved_by_name: null,
    lines: [{ line_no: 1, product_id: 5, sku: "APL-AP4", name: "AirPods 4", quantity: 1, unit_price: "189.00",
      line_total: "189.00" }],
  };
}

const buttons = () => screen.queryAllByRole("button").map((button) => button.textContent);
const show = (detail: ReturnDetail, me: Me) =>
  render(<ReturnActions detail={detail} me={me} onChanged={() => {}} onStale={() => {}} />);

describe("which return actions a staff member gets", () => {
  it("any_retail_store_can_receive_a_requested_return", () => {
    show(aReturn("requested"), isla);
    expect(buttons()).toEqual(["Receive at Bondi Junction"]);
  });

  it("the_receiving_store_refunds_or_rejects", () => {
    show(aReturn("received", 1), aiden);
    expect(buttons()).toEqual(["Refund $189.00…", "Reject…"]);
  });

  it("another_store_cannot_finish_a_return_it_did_not_receive", () => {
    show(aReturn("received", 1), isla);
    expect(buttons()).toEqual([]);
    expect(screen.getByText(/Received at Sydney CBD/)).toBeTruthy();
  });

  it("support_reads_but_does_not_act", () => {
    show(aReturn("requested"), nora);
    expect(buttons()).toEqual([]);
  });

  it("a_final_return_has_no_actions", () => {
    show(aReturn("refunded", 1), aiden);
    expect(buttons()).toEqual([]);
  });
});

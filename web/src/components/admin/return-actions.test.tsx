import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError, type Me, type ReturnDetail } from "@/lib/api/client";

import { ReturnActions } from "./return-actions";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
  call: <T,>(request: Promise<T>) => request,
}));

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

describe("when someone else got there first", () => {
  it("a_second_refund_shows_why_after_the_page_reloads", async () => {
    // Two staff press Refund: the second gets 409 and the page reloads. The reloaded return is final, so it has
    // no buttons, but the second person must still see that someone else refunded it.
    api.POST.mockRejectedValueOnce(new ApiError(409, "return_status_transition",
      "This return is already refunded, so it can't be refunded now.", { status: "refunded" }));
    const onStale = vi.fn();
    const { rerender } = render(<ReturnActions detail={aReturn("received", 1)} me={aiden} onChanged={() => {}}
      onStale={onStale} />);
    fireEvent.click(screen.getByRole("button", { name: "Refund $189.00…" }));
    fireEvent.click(screen.getByRole("button", { name: "Restock and refund $189.00" }));
    await screen.findByText(/already refunded/);
    expect(onStale).toHaveBeenCalledOnce();
    rerender(<ReturnActions detail={aReturn("refunded", 1)} me={aiden} onChanged={() => {}} onStale={onStale} />);
    expect(screen.getByText(/already refunded/)).toBeTruthy();
  });

  it("a_receipt_by_another_store_meanwhile_reloads_the_page", async () => {
    // Bondi receives it while Sydney's page still says requested: Sydney's click is refused as other_store.
    api.POST.mockRejectedValueOnce(new ApiError(403, "other_store", "Only the store that received this return can act on it."));
    const onStale = vi.fn();
    render(<ReturnActions detail={aReturn("requested")} me={aiden} onChanged={() => {}} onStale={onStale} />);
    fireEvent.click(screen.getByRole("button", { name: "Receive at Sydney CBD" }));
    await screen.findByText(/Only the store that received/);
    expect(onStale).toHaveBeenCalledOnce();
  });
});

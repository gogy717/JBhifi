import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type Me, type OrderDetail } from "@/lib/api/client";

import { ReturnRequestForm } from "./return-request-form";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
  call: <T,>(request: Promise<T>) => request,
}));

const customer: Me = { kind: "customer", id: 9, display_name: "Alice", store_id: null, store_name: null,
  staff_type: null, runs_store: false };
const collected = {
  order_id: 3, customer_id: 9, status: "collected",
  history: [{ seq: 1, from_status: null, to_status: "collected", changed_at: new Date().toISOString(),
    changed_by_staff_id: null, changed_by_name: null }],
  lines: [{ line_no: 1, product_id: 5, sku: "APL-AP4", name: "AirPods 4", quantity: 2, unit_price: "189.00",
    line_total: "378.00" }],
} as unknown as OrderDetail;

const keysSent = () => api.POST.mock.calls.map(([, options]) => options.params.header["Idempotency-Key"]);

async function askForOne() {
  fireEvent.change(await screen.findByLabelText("How many AirPods 4 to return"), { target: { value: "1" } });
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Too big" } });
  fireEvent.click(screen.getByRole("button", { name: "Request return" }));
}

describe("a return request whose answer is uncertain", () => {
  beforeEach(() => {
    api.GET.mockReset().mockResolvedValue([]);
    api.POST.mockReset();
  });

  it("a_sign_in_failure_keeps_the_key_for_the_retry", async () => {
    // The first answer was lost, and by the retry the sign-in had lapsed: 401 says nothing about whether the first
    // try got through, so the request stays exactly as sent, with its key.
    api.POST.mockRejectedValueOnce(new ApiError(0, "network_error", "No answer"))
      .mockRejectedValueOnce(new ApiError(401, "not_signed_in", "Sign in to do that."));
    render(<ReturnRequestForm order={collected} me={customer} />);
    await askForOne();
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    const retry = await screen.findByRole("button", { name: "Try again" });
    expect(screen.getByLabelText("How many AirPods 4 to return")).toHaveProperty("disabled", true);
    fireEvent.click(retry);
    await screen.findByText(/couldn.t confirm/);
    expect(new Set(keysSent()).size).toBe(1);
    expect(keysSent()).toHaveLength(3);
  });

  it("a_refusal_frees_the_form_and_the_next_request_gets_a_new_key", async () => {
    api.POST.mockRejectedValueOnce(new ApiError(409, "br12_return_qty_within_purchased", "Too many"))
      .mockRejectedValueOnce(new ApiError(409, "br12_return_qty_within_purchased", "Too many"));
    render(<ReturnRequestForm order={collected} me={customer} />);
    await askForOne();
    fireEvent.click(await screen.findByRole("button", { name: "Request return" }));
    await screen.findAllByText("Too many");
    expect(keysSent()).toHaveLength(2);
    expect(new Set(keysSent()).size).toBe(2);
  });
});

/**
 * T12: the buttons on an order come from the server's `allowed_actions`, the status the screen is showing
 * is what gets submitted, a colleague's move is reported rather than overwritten, and a double-click
 * cannot send twice.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const harness = vi.hoisted(() => ({
  calls: [] as { method: string; path: string; init?: Record<string, unknown> }[],
  replies: [] as unknown[],
}));

vi.mock("@/lib/api/client", () => {
  class ApiError extends Error {
    constructor(readonly status: number, readonly code: string, message: string, readonly detail?: unknown) {
      super(message);
    }
    get isRule() {
      return false;
    }
    get isConflict() {
      return this.status === 409;
    }
  }
  const respond = (method: string) => (path: string, init?: Record<string, unknown>) => {
    harness.calls.push({ method, path, init });
    const reply = harness.replies.shift();
    if (reply instanceof ApiError) return Promise.reject(reply);
    if (reply instanceof Promise) return reply;                 // a deferred reply, for the in-flight case
    return Promise.resolve({ data: reply });
  };
  return {
    ApiError,
    toApiError: (error: unknown) =>
      (error instanceof ApiError ? error : new ApiError(0, "client_error", String(error))),
    call: (outcome: Promise<{ data?: unknown }>) => outcome.then((response) => response.data),
    api: { GET: respond("GET"), POST: respond("POST"), PATCH: respond("PATCH") },
  };
});

import { ApiError } from "@/lib/api/client";
import { OrderActions } from "./order-actions";

const ORDER = {
  order_id: 12,
  customer_id: 3,
  placed_at: "2026-09-20T02:00:00Z",
  status: "paid",
  fulfilment_method: "delivery",
  fulfilling_store_id: 13,
  fulfilling_store_name: "Eastern Creek DC",
  total: "1598.00",
  line_count: 1,
  lines: [
    { line_no: 1, product_id: 1, sku: "MS-XSX-1TB", name: "Xbox Series X", quantity: 2,
      unit_price: "799.00", line_total: "1598.00" },
  ],
  delivery_address: { address_no: 1, line1: "12 Harris St", suburb: "Pyrmont", state: "NSW", postcode: "2009" },
  payments: [{ payment_id: 1, kind: "charge", amount: "1598.00", return_id: null, cancellation_id: null,
    created_at: "2026-09-20T02:00:00Z" }],
  history: [],
  allowed_actions: ["picking", "cancel"],
  return_eligibility: { eligible: false, deadline: null, reason: "not delivered yet", lines: [] },
} as unknown as Parameters<typeof OrderActions>[0]["order"];

const user = () => userEvent.setup();

beforeEach(() => {
  harness.calls = [];
  harness.replies = [];
});

describe("the staff order actions", () => {
  it("offers exactly the moves the server allowed, and nothing else", () => {
    render(<OrderActions order={ORDER} onChanged={() => {}} />);
    expect(screen.getByRole("button", { name: "Start picking" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel order…" })).toBeInTheDocument();
    // A delivery order never becomes ready or collected: those are click & collect moves.
    expect(screen.queryByRole("button", { name: /Ready/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Collected/i })).not.toBeInTheDocument();
  });

  it("says so when there is nothing left to do", () => {
    const done = { ...ORDER, status: "delivered", allowed_actions: [] } as unknown as typeof ORDER;
    render(<OrderActions order={done} onChanged={() => {}} />);
    expect(screen.getByText(/Nothing to do/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Start picking|Mark / })).not.toBeInTheDocument();
  });

  it("submits the status the screen was showing, and reports a colleague's move", async () => {
    const onChanged = vi.fn();
    render(<OrderActions order={ORDER} onChanged={onChanged} />);
    harness.replies = [new ApiError(409, "stale_status", "This order has already moved on.",
      { status: "picking" })];

    await user().click(screen.getByRole("button", { name: "Start picking" }));

    await waitFor(() => expect(harness.calls).toHaveLength(1));
    expect(harness.calls[0]).toMatchObject({
      method: "PATCH",
      path: "/api/v1/orders/{order_id}/status",
      init: { params: { path: { order_id: 12 } }, body: { to_status: "picking", expected_status: "paid" } },
    });
    expect(await screen.findByText(/Someone else moved this order first/)).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledWith(ORDER);          // the page is told to re-read the order
  });

  it("cannot send the same move twice while the first is in flight", async () => {
    let release: (value: unknown) => void = () => {};
    harness.replies = [new Promise((resolve) => { release = resolve; })];
    const onChanged = vi.fn();
    render(<OrderActions order={ORDER} onChanged={onChanged} />);

    const button = screen.getByRole("button", { name: "Start picking" });
    await user().click(button);
    expect(button).toBeDisabled();                          // it says "Saving…" and cannot be clicked again
    await user().click(button);
    expect(harness.calls).toHaveLength(1);

    release({ data: { ...ORDER, status: "picking", allowed_actions: ["shipped", "cancel"] } });
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });

  it("asks for a reason before cancelling, and shows what it will cost", async () => {
    const onChanged = vi.fn();
    render(<OrderActions order={ORDER} onChanged={onChanged} />);
    await user().click(screen.getByRole("button", { name: "Cancel order…" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Eastern Creek DC");   // where the stock goes back to
    expect(dialog).toHaveTextContent("$1,598.00");          // the refund
    expect(dialog).toHaveTextContent("back to stock");
    expect(screen.getByRole("button", { name: "Cancel and refund" })).toBeDisabled();

    harness.replies = [{ ...ORDER, status: "cancelled", allowed_actions: [] }];
    await user().type(screen.getByLabelText("Why is it being cancelled?"), "customer changed their mind");
    await user().click(screen.getByRole("button", { name: "Cancel and refund" }));

    await waitFor(() => expect(harness.calls.at(-1)).toMatchObject({
      method: "POST",
      path: "/api/v1/orders/{order_id}/cancel",
      init: { params: { path: { order_id: 12 } },
        body: { expected_status: "paid", reason: "customer changed their mind" } },
    }));
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ status: "cancelled" }));
  });
});

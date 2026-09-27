/**
 * T15: the returns desk offers Receive, Reject and Process only when the server says this store may do
 * them in this state; processing is confirmed with the exact refund; and nothing can be sent twice.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
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
    if (reply instanceof Promise) return reply;
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
import { ReturnActions } from "./return-actions";

const RETURN = {
  return_id: 7,
  order_id: 12,
  status: "requested",
  requested_at: "2026-09-10T02:00:00Z",
  reason: "changed my mind",
  refund_amount: null,
  lines: [
    { line_no: 1, product_id: 1, sku: "MS-XSX-1TB", name: "Xbox Series X", quantity: 1,
      unit_price: "799.00", line_total: "799.00" },
  ],
  receiving_store: null,
  history: [],
  allowed_actions: ["receive", "reject"],
  refund_preview: "799.00",
} as unknown as Parameters<typeof ReturnActions>[0]["detail"];

const user = () => userEvent.setup();

beforeEach(() => {
  harness.calls = [];
  harness.replies = [];
});

describe("the returns desk actions", () => {
  it("offers only what this store may do in this state", () => {
    render(<ReturnActions detail={RETURN} onChanged={() => {}} />);
    expect(screen.getByRole("button", { name: "Receive it" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject the return" })).toBeInTheDocument();
    // Processing is only possible once the item is in the store's hands.
    expect(screen.queryByRole("button", { name: "Process the refund" })).not.toBeInTheDocument();
  });

  it("does nothing for a return this store has no part in", () => {
    const elsewhere = { ...RETURN, allowed_actions: [] } as unknown as typeof RETURN;
    render(<ReturnActions detail={elsewhere} onChanged={() => {}} />);
    expect(screen.getByText(/Nothing for this store to do/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("receives with the status the screen was showing, and reports a colleague's move", async () => {
    const onChanged = vi.fn();
    render(<ReturnActions detail={RETURN} onChanged={onChanged} />);
    harness.replies = [new ApiError(409, "stale_status", "This return has already moved on.",
      { status: "received" })];

    await user().click(screen.getByRole("button", { name: "Receive it" }));

    await waitFor(() => expect(harness.calls).toHaveLength(1));
    expect(harness.calls[0]).toMatchObject({
      method: "POST",
      path: "/api/v1/returns/{return_id}/receive",
      init: { params: { path: { return_id: 7 } }, body: { expected_status: "requested" } },
    });
    expect(await screen.findByText(/This return moved on/)).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledWith(RETURN);
  });

  it("confirms a refund with the amount and the quantities before sending it", async () => {
    const received = { ...RETURN, status: "received", allowed_actions: ["reject", "process"],
      receiving_store: { store_id: 1, name: "Sydney CBD" } } as unknown as typeof RETURN;
    const onChanged = vi.fn();
    render(<ReturnActions detail={received} onChanged={onChanged} />);

    await user().click(screen.getByRole("button", { name: "Process the refund" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Sydney CBD");        // where it will be restocked
    expect(dialog).toHaveTextContent("$799.00");           // the refund
    expect(dialog).toHaveTextContent("1 × Xbox Series X"); // the exact quantity going back

    harness.replies = [{ ...received, status: "refunded", refund_amount: "799.00", allowed_actions: [] }];
    await user().click(within(dialog).getByRole("button", { name: "Process the refund" }));

    await waitFor(() => expect(harness.calls.at(-1)).toMatchObject({
      method: "POST",
      path: "/api/v1/returns/{return_id}/process",
      init: { params: { path: { return_id: 7 } }, body: { expected_status: "received" } },
    }));
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ status: "refunded" }));
  });

  it("explains that rejecting is final, and cannot send twice while one is in flight", async () => {
    let release: (value: unknown) => void = () => {};
    harness.replies = [new Promise((resolve) => { release = resolve; })];
    render(<ReturnActions detail={RETURN} onChanged={() => {}} />);

    await user().click(screen.getByRole("button", { name: "Reject the return" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/Rejecting is final and refunds nothing/);

    const confirm = within(dialog).getByRole("button", { name: "Reject the return" });
    await user().click(confirm);
    await user().click(confirm);
    expect(harness.calls).toHaveLength(1);

    release({ data: { ...RETURN, status: "rejected", allowed_actions: [] } });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

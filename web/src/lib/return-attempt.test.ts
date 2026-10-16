import { describe, expect, it } from "vitest";

import { attemptFor, returnable, returnDeadline } from "./return-attempt";

const keys = () => {
  let n = 0;
  return () => `key-${++n}`;
};

describe("what is left to return", () => {
  const bought = [{ line_no: 1, quantity: 2 }, { line_no: 2, quantity: 1 }];

  it("returnable_subtracts_open_and_refunded_returns", () => {
    const left = returnable(bought, [
      { order_id: 7, status: "requested", lines: [{ line_no: 1, quantity: 1 }] },
      { order_id: 7, status: "refunded", lines: [{ line_no: 2, quantity: 1 }] },
    ], 7);
    expect([...left]).toEqual([[1, 1], [2, 0]]);
  });

  it("returnable_ignores_rejected_returns", () => {
    // A rejected return no longer counts (BR12): its units can be asked for again.
    const left = returnable(bought, [{ order_id: 7, status: "rejected", lines: [{ line_no: 1, quantity: 2 }] }], 7);
    expect([...left]).toEqual([[1, 2], [2, 1]]);
  });

  it("returnable_ignores_other_orders", () => {
    const left = returnable(bought, [{ order_id: 8, status: "requested", lines: [{ line_no: 1, quantity: 2 }] }], 7);
    expect(left.get(1)).toBe(2);
  });
});

describe("the retry key of a return request", () => {
  const body = { reason: "Too big", lines: [{ line_no: 2, quantity: 1 }, { line_no: 1, quantity: 1 }] };

  it("a_retry_of_the_same_request_keeps_its_key", () => {
    const next = keys();
    const first = attemptFor(undefined, 7, body, next);
    // The same request again — lines in another order, the reason with extra spaces, a 0 left in — is a retry.
    const again = attemptFor(first, 7, {
      reason: "  Too big ", lines: [{ line_no: 1, quantity: 1 }, { line_no: 3, quantity: 0 }, { line_no: 2, quantity: 1 }],
    }, next);
    expect(first.key).toBe("key-1");
    expect(again).toBe(first);
  });

  it("an_edited_request_gets_a_new_key", () => {
    const next = keys();
    const first = attemptFor(undefined, 7, body, next);
    expect(attemptFor(first, 7, { ...body, reason: "Faulty" }, next).key).toBe("key-2");
    expect(attemptFor(first, 7, { ...body, lines: [{ line_no: 1, quantity: 2 }] }, next).key).toBe("key-3");
    expect(attemptFor(first, 8, body, next).key).toBe("key-4");               // another order
  });
});

describe("the 30-day window", () => {
  it("return_deadline_is_30_days_after_completion", () => {
    const history = [
      { seq: 1, to_status: "placed", changed_at: "2026-10-01T09:00:00Z" },
      { seq: 5, to_status: "collected", changed_at: "2026-10-03T09:00:00Z" },
      { seq: 2, to_status: "paid", changed_at: "2026-10-01T09:00:00Z" },
    ];
    expect(returnDeadline("collected", history)?.toISOString()).toBe("2026-11-02T09:00:00.000Z");
    expect(returnDeadline("paid", history)).toBeUndefined();
  });
});

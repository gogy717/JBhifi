import { beforeEach, describe, expect, it } from "vitest";

import { ATTEMPT_STORAGE_KEY, attemptFingerprint, clearAttempt, getOrCreateAttempt, pendingAttempt,
  twoDecimals } from "./checkout-attempt";

const body = {
  fulfilment_method: "click_collect" as const,
  fulfilling_store_id: 1,
  delivery_address_no: null,
  items: [{ product_id: 3, quantity: 1 }, { product_id: 2, quantity: 2 }],
  expected_total: "39.90",
};

describe("the reviewed checkout attempt", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("same_attempt_reuses_key", () => {
    const first = getOrCreateAttempt(1, body);
    const again = getOrCreateAttempt(1, body);
    expect(again.key).toBe(first.key);
    // The same review with the lines in another order is still the same review.
    const reordered = getOrCreateAttempt(1, { ...body, items: [...body.items].reverse() });
    expect(reordered.key).toBe(first.key);
    expect(twoDecimals("19.9")).toBe("19.90");
  });

  it("changed_payload_uses_new_key", () => {
    const first = getOrCreateAttempt(1, body);
    expect(getOrCreateAttempt(1, { ...body, expected_total: "40.00" }).key).not.toBe(first.key);
    expect(getOrCreateAttempt(1, { ...body, fulfilment_method: "delivery", delivery_address_no: 1 }).key)
      .not.toBe(first.key);
    expect(getOrCreateAttempt(1, { ...body, items: [{ product_id: 3, quantity: 2 }] }).key).not.toBe(first.key);
  });

  it("customer_switch_discards_pending_attempt", () => {
    const first = getOrCreateAttempt(1, body);
    const other = getOrCreateAttempt(2, body);
    expect(other.key).not.toBe(first.key);
    expect(other.customer_id).toBe(2);
    expect(pendingAttempt()?.customer_id).toBe(2);      // the first customer's attempt is gone
    // And switching back is a new attempt too, not the old key resurrected.
    expect(getOrCreateAttempt(1, body).key).not.toBe(first.key);
  });

  it("unknown_outcome_preserves_body_and_key", () => {
    const attempt = getOrCreateAttempt(1, body);
    const kept = pendingAttempt();
    expect(kept).toEqual(attempt);
    expect(kept?.body).toEqual(body);
    clearAttempt();
    expect(pendingAttempt()).toBeUndefined();
  });

  it("ignores whatever else may be in that storage slot", () => {
    window.sessionStorage.setItem(ATTEMPT_STORAGE_KEY, "{not json}");
    expect(pendingAttempt()).toBeUndefined();
    window.sessionStorage.setItem(ATTEMPT_STORAGE_KEY, JSON.stringify({ hello: "world" }));
    expect(pendingAttempt()).toBeUndefined();
  });

  it("fingerprints the reviewed body, not the object identity", () => {
    expect(attemptFingerprint(body)).toBe(attemptFingerprint({ ...body }));
    expect(attemptFingerprint(body)).not.toBe(attemptFingerprint({ ...body, fulfilling_store_id: 2 }));
  });
});

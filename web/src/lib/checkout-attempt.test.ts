import { beforeEach, describe, expect, it, vi } from "vitest";

import { ATTEMPT_STORAGE_KEY, attemptFingerprint, clearAttempt, getOrCreateAttempt, keepsAttempt,
  pendingAttempt, twoDecimals } from "./checkout-attempt";

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
    clearAttempt();                         // and the memory copy
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

  it("keeps the key unless the API refused the basket", () => {
    // Unknown outcome, or a sign-in problem that says nothing about an earlier try: keep key and body.
    for (const status of [0, 500, 503, 401, 403]) expect(keepsAttempt(status)).toBe(true);
    // The API refused this basket: nothing was placed, so the next review gets a new key.
    for (const status of [404, 409, 422]) expect(keepsAttempt(status)).toBe(false);
  });

  it("keeps the attempt in this page's memory when storage is blocked", () => {
    const blocked = () => {
      throw new DOMException("The operation is insecure.", "SecurityError");
    };
    const spies = [
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(blocked),
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(blocked),
      vi.spyOn(Storage.prototype, "removeItem").mockImplementation(blocked),
    ];
    try {
      const attempt = getOrCreateAttempt(1, body);
      // Within this page (client-side navigation included) the same review keeps its key.
      expect(pendingAttempt()).toEqual(attempt);
      expect(getOrCreateAttempt(1, body).key).toBe(attempt.key);
      clearAttempt();
      expect(pendingAttempt()).toBeUndefined();
    } finally {
      for (const spy of spies) spy.mockRestore();
    }
  });
});

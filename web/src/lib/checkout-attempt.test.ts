import { beforeEach, describe, expect, it, vi } from "vitest";

import { ATTEMPT_STORAGE_KEY, attemptFingerprint, clearAttempt, getOrCreateAttempt, inFlightSend, keepsAttempt,
  pendingAttempt, sendAttempt, twoDecimals } from "./checkout-attempt";

const body = {
  fulfilment_method: "click_collect" as const,
  fulfilling_store_id: 1,
  delivery_address_no: null,
  items: [{ product_id: 3, quantity: 1 }, { product_id: 2, quantity: 2 }],
  expected_total: "39.90",
};

describe("the reviewed checkout attempt", () => {
  beforeEach(() => {
    window.localStorage.clear();
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
    window.localStorage.setItem(ATTEMPT_STORAGE_KEY, "{not json}");
    expect(pendingAttempt()).toBeUndefined();
    window.localStorage.setItem(ATTEMPT_STORAGE_KEY, JSON.stringify({ hello: "world" }));
    expect(pendingAttempt()).toBeUndefined();
    // typeof null is "object": a record without a body must not reach the checkout page.
    window.localStorage.setItem(ATTEMPT_STORAGE_KEY, JSON.stringify({ customer_id: 1, key: "k", fingerprint: "f",
      body: null }));
    expect(pendingAttempt()).toBeUndefined();
  });

  it("an attempt stored by another tab is pending here", () => {
    // Another tab of this browser kept a try that got no answer: this tab sees it, and the same review reuses its key.
    const elsewhere = { customer_id: 1, key: "11111111-1111-4111-8111-111111111111", fingerprint: attemptFingerprint(body),
      body };
    window.localStorage.setItem(ATTEMPT_STORAGE_KEY, JSON.stringify(elsewhere));
    expect(pendingAttempt()).toEqual(elsewhere);
    expect(getOrCreateAttempt(1, body).key).toBe(elsewhere.key);
  });

  it("a late answer clears only its own attempt", () => {
    const first = getOrCreateAttempt(1, body);
    const newer = getOrCreateAttempt(1, { ...body, expected_total: "40.00" });   // a newer review replaced it
    clearAttempt(first.key);                                                    // the first try's answer comes late
    expect(pendingAttempt()?.key).toBe(newer.key);
    clearAttempt(newer.key);
    expect(pendingAttempt()).toBeUndefined();
  });

  it("marks a send in flight until it settles, answer or failure", async () => {
    const attempt = getOrCreateAttempt(1, body);
    let answer!: (value: string) => void;
    const request = sendAttempt(attempt, () => new Promise<string>((resolve) => { answer = resolve; }));
    const running = inFlightSend(attempt.key);
    expect(running).toBeDefined();
    expect(inFlightSend("another key")).toBeUndefined();
    answer("placed");
    await expect(request).resolves.toBe("placed");
    await running;
    expect(inFlightSend(attempt.key)).toBeUndefined();

    // A failed send settles too, and the promise the page waits on never rejects.
    const failing = sendAttempt(attempt, () => Promise.reject(new Error("offline")));
    const settled = inFlightSend(attempt.key);
    await expect(failing).rejects.toThrow("offline");
    await expect(settled).resolves.toBeUndefined();
    expect(inFlightSend(attempt.key)).toBeUndefined();
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

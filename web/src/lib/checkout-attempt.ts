/**
 * One reviewed checkout attempt, remembered across an uncertain network outcome.

 * If the response never arrives, the customer has to be able to send *exactly* the same request again:
 * same Idempotency-Key and same body, so the API either creates one order or replays the one it already
 * created. Changing the review (a different address, quantity or total) is a different attempt and gets a
 * fresh key. The attempt is kept per customer, in sessionStorage, and never holds anything secret.
 */

export type CheckoutAttemptBody = {
  fulfilment_method: "delivery" | "click_collect";
  fulfilling_store_id: number;
  delivery_address_no?: number | null;
  items: { product_id: number; quantity: number }[];
  expected_total: string;
};

export type CheckoutAttempt = {
  customer_id: number;
  key: string;
  fingerprint: string;
  body: CheckoutAttemptBody;
};

export const ATTEMPT_STORAGE_KEY = "jb.shop.checkoutAttempt";

/** Money as two decimals, so "19.9" and "19.90" are the same review. */
export function twoDecimals(value: string | number): string {
  const [whole, fraction = ""] = String(value).trim().split(".");
  const negative = whole.startsWith("-");
  const digits = (negative ? whole.slice(1) : whole).replace(/\D/g, "") || "0";
  return `${negative ? "-" : ""}${digits}.${(fraction.replace(/\D/g, "") + "00").slice(0, 2)}`;
}

/** A stable summary of what the customer reviewed: same review, same fingerprint. */
export function attemptFingerprint(body: CheckoutAttemptBody): string {
  return JSON.stringify({
    fulfilment_method: body.fulfilment_method,
    fulfilling_store_id: body.fulfilling_store_id,
    delivery_address_no: body.delivery_address_no ?? null,
    expected_total: twoDecimals(body.expected_total),
    items: [...body.items]
      .sort((left, right) => left.product_id - right.product_id)
      .map((item) => ({ product_id: item.product_id, quantity: item.quantity })),
  });
}

/** A fresh Idempotency-Key. Exported so the return form uses the same generator. */
export function newAttemptKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (digit) =>
    (Number(digit) ^ (Math.random() * 16 >> Number(digit) / 4)).toString(16));
}

export function pendingAttempt(): CheckoutAttempt | undefined {
  try {
    const raw = window.sessionStorage.getItem(ATTEMPT_STORAGE_KEY);
    if (!raw) return undefined;
    const parsed = JSON.parse(raw) as CheckoutAttempt | null;
    return parsed && typeof parsed.key === "string" && typeof parsed.customer_id === "number"
      ? parsed : undefined;
  } catch {
    return undefined;                       // storage blocked, or something else wrote this key
  }
}

/**
 * The attempt to send. A stored attempt is reused only when it is for this customer *and* this exact
 * review; anything else (including a customer switch) starts a new attempt with a new key.
 */
export function getOrCreateAttempt(customerId: number, body: CheckoutAttemptBody): CheckoutAttempt {
  const fingerprint = attemptFingerprint(body);
  const stored = pendingAttempt();
  if (stored && stored.customer_id === customerId && stored.fingerprint === fingerprint) return stored;
  const attempt: CheckoutAttempt = { customer_id: customerId, key: newAttemptKey(), fingerprint, body };
  try {
    window.sessionStorage.setItem(ATTEMPT_STORAGE_KEY, JSON.stringify(attempt));
  } catch {
    // The attempt still works for this page view; a reload would create a new key, which the API can
    // still resolve because the old key and the new one produce at most one order each.
  }
  return attempt;
}

export function clearAttempt(): void {
  try {
    window.sessionStorage.removeItem(ATTEMPT_STORAGE_KEY);
  } catch {
    // nothing to clear
  }
}

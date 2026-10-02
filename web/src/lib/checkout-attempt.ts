/**
 * One reviewed checkout attempt, remembered across an uncertain network outcome.
 *
 * If the response never arrives, the customer must be able to send *exactly* the same request again: same
 * Idempotency-Key and same body, so the API either creates one order or returns the one it already created
 * (BR10). Changing the review (another address, store, quantity or total) is a different attempt and gets a
 * fresh key. The API replays whatever order a customer placed with a key, without comparing bodies, so it is
 * this fingerprint — kept only in the browser — that gives a changed review its own key.
 *
 * The attempt is kept per customer in sessionStorage (this tab only, so it survives a reload) and holds nothing
 * secret. When storage is blocked it is kept in memory, which lasts until the page reloads.
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

/** A fresh Idempotency-Key: a random (version 4) UUID — the API refuses a key that isn't a UUID. */
export function newAttemptKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  // crypto.randomUUID needs a secure context (https, localhost or 127.0.0.1); elsewhere, build one by hand.
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (digit) =>
    (Number(digit) ^ (Math.random() * 16 >> Number(digit) / 4)).toString(16));
}

/** The attempt held in memory: the only copy when sessionStorage is blocked. */
let remembered: CheckoutAttempt | undefined;

export function pendingAttempt(): CheckoutAttempt | undefined {
  let raw: string | null;
  try {
    raw = window.sessionStorage.getItem(ATTEMPT_STORAGE_KEY);
  } catch {
    return remembered;                      // storage blocked: this page's memory
  }
  if (!raw) return undefined;
  try {
    const parsed = JSON.parse(raw) as CheckoutAttempt | null;
    return parsed && typeof parsed.key === "string" && typeof parsed.customer_id === "number"
      && typeof parsed.fingerprint === "string" && typeof parsed.body === "object" ? parsed : undefined;
  } catch {
    return undefined;                       // something else wrote this key
  }
}

/** Keep the attempt for a retry: in memory, and in sessionStorage so it survives a reload of this tab. */
function remember(attempt: CheckoutAttempt): void {
  remembered = attempt;
  try {
    window.sessionStorage.setItem(ATTEMPT_STORAGE_KEY, JSON.stringify(attempt));
  } catch {
    // Storage blocked: the memory copy lasts until the page reloads. After a reload the same review gets a new
    // key, so a response lost just before it could then end in a second order.
  }
}

/**
 * The attempt to send. A stored attempt is reused only when it is for this customer *and* this exact review;
 * anything else — including someone else signing in on this browser — starts a new attempt with a new key,
 * which replaces the stored one. So the checkout page calls this only when none of this customer's tries is
 * waiting for an answer: replacing a waiting try would lose the key that may have placed an order.
 */
export function getOrCreateAttempt(customerId: number, body: CheckoutAttemptBody): CheckoutAttempt {
  const fingerprint = attemptFingerprint(body);
  const stored = pendingAttempt();
  if (stored && stored.customer_id === customerId && stored.fingerprint === fingerprint) return stored;
  const attempt: CheckoutAttempt = { customer_id: customerId, key: newAttemptKey(), fingerprint, body };
  remember(attempt);
  return attempt;
}

/** The attempt got its answer (its order, or a refusal), or the customer started a new order instead. */
export function clearAttempt(): void {
  remembered = undefined;
  try {
    window.sessionStorage.removeItem(ATTEMPT_STORAGE_KEY);
  } catch {
    // storage blocked: nothing stored there
  }
}

/**
 * After a send that failed, keep the pending attempt (its key and body) for "Try again"? Yes when the outcome is
 * unknown — no answer (0), a server error (≥ 500), or a sign-in problem (401/403) that says nothing about whether
 * an earlier try with this key went through. No when the API refused the basket (404/409/422): nothing was
 * placed, so the next review gets a new key.
 */
export function keepsAttempt(status: number): boolean {
  return status === 0 || status >= 500 || status === 401 || status === 403;
}

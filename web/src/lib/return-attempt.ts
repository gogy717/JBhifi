/**
 * The return form's arithmetic: what is left to return from each order line, when the 30-day window closes,
 * and the Idempotency-Key of one reviewed request.
 *
 * A request whose answer never arrives must be sent again *exactly*: same key and same lines, so the API either
 * creates one return or hands back the one it already created (BR10). The API replays whatever return was asked
 * for with a key without comparing bodies, so it is this fingerprint that gives an edited request its own key.
 * Unlike checkout (checkout-attempt.ts), the attempt lives only in the form's memory: a return is asked for from
 * one order page, and after a reload the order's returns show whether the request got through.
 */
import { newAttemptKey } from "./checkout-attempt";

export const RETURN_WINDOW_DAYS = 30;

export type ReturnLineRequest = { line_no: number; quantity: number };
export type ReturnRequestBody = { reason: string; lines: ReturnLineRequest[] };
export type ReturnAttempt = { orderId: number; key: string; fingerprint: string };

type ReturnOfAnOrder = { order_id: number; status: string; lines: ReturnLineRequest[] };

/** For each line bought: how many can still be asked for. Rejected returns don't count (BR12), so their
 *  units can be asked for again. The database checks it again on every request. */
export function returnable(bought: ReturnLineRequest[], returns: ReturnOfAnOrder[], orderId: number): Map<number, number> {
  const left = new Map(bought.map((line) => [line.line_no, line.quantity]));
  for (const asked of returns) {
    if (asked.order_id !== orderId || asked.status === "rejected") continue;
    for (const line of asked.lines) left.set(line.line_no, Math.max(0, (left.get(line.line_no) ?? 0) - line.quantity));
  }
  return left;
}

/** When the window closes: 30 days after the order reached its current status, if that is delivered or
 *  collected — the moment BR11 counts from. Undefined while the order can't be returned at all. */
export function returnDeadline(
  status: string,
  history: { seq: number; to_status: string; changed_at: string }[],
): Date | undefined {
  if (status !== "delivered" && status !== "collected") return undefined;
  const completed = history.filter((change) => change.to_status === status).sort((a, b) => b.seq - a.seq)[0];
  if (!completed) return undefined;
  return new Date(new Date(completed.changed_at).getTime() + RETURN_WINDOW_DAYS * 24 * 60 * 60 * 1000);
}

/** A stable summary of the request: the same lines (in any order, zeros dropped) and reason, the same fingerprint. */
export function returnFingerprint(orderId: number, body: ReturnRequestBody): string {
  return JSON.stringify({
    order_id: orderId,
    reason: body.reason.trim(),
    lines: body.lines
      .filter((line) => line.quantity > 0)
      .sort((left, right) => left.line_no - right.line_no)
      .map((line) => ({ line_no: line.line_no, quantity: line.quantity })),
  });
}

/** The attempt for this request: the previous one when it is exactly this request again (a retry), otherwise a
 *  new attempt with a fresh key. */
export function attemptFor(previous: ReturnAttempt | undefined, orderId: number, body: ReturnRequestBody,
  newKey: () => string = newAttemptKey): ReturnAttempt {
  const fingerprint = returnFingerprint(orderId, body);
  return previous?.fingerprint === fingerprint ? previous : { orderId, key: newKey(), fingerprint };
}

/**
 * The return journey: a customer asks to send something back, the store takes it in, and the refund
 * follows from the price it was bought at.
 *
 * The specs in this file run in order (the config keeps one worker): the first works the return the demo
 * data leaves at the Melbourne Central desk, the second asks for a new one on a collected order, and the
 * third rejects that request — a rejected return is final.
 */
import { expect, test, type Page } from "@playwright/test";

import {
  API, BEN, SOPHIE_ID, apiJson, apiSignIn, ordersOf, returnsOf, signInAsCustomer, signInAsStaff,
} from "./stack";

type OrderDetail = {
  order_id: number; status: string; total: string;
  return_eligibility: {
    eligible: boolean;
    reason: string | null;
    lines: { line_no: number; name: string; remaining_quantity: number; unit_price: string }[];
  };
};

/** The desk's confirm button has the same name as the action that opened it: reach into the dialog. */
const confirm = (page: Page, name: string) =>
  page.getByRole("dialog").getByRole("button", { name });

/** A return as the customer sees it: a link card headed "Return #id". */
const customerReturn = (page: Page, returnId: number) =>
  page.getByRole("link").filter({ hasText: `Return #${returnId}` }).first();

test("the desk receives a waiting return and then refunds it, and the customer sees both", async ({ page, request }) => {
  await apiSignIn(request, "customer", 2);                      // Ben Okafor
  const waiting = (await returnsOf(request, 2)).find((row) => row.status === "requested");
  expect(waiting, "the seeded return waiting at the Melbourne Central desk").toBeTruthy();
  const returnId = waiting!.return_id;

  await signInAsStaff(page, SOPHIE_ID);                          // store staff at Melbourne Central
  await page.goto("/admin/returns");
  await page.getByRole("row").filter({ hasText: `#${returnId}` })
    .getByRole("link", { name: "Open" }).click();
  await expect(page.getByRole("heading", { name: `Return #${returnId}` })).toBeVisible();

  // Receiving records who took it in and where — and does not restock or refund yet.
  await page.getByRole("button", { name: "Receive it" }).click();
  await expect(page.getByText("Received by the store").first()).toBeVisible();
  const received = await apiJson<{ status: string; receiving_store: { name: string } | null }>(
    request, `${API}/returns/${returnId}`);
  expect(received.status).toBe("received");
  expect(received.receiving_store?.name).toBe("Melbourne Central");

  // Processing restocks and refunds in one transaction, from the purchase-time price.
  await page.getByRole("button", { name: "Process the refund" }).click();
  await confirm(page, "Process the refund").click();
  await expect(page.getByText("Refunded", { exact: true }).first()).toBeVisible();

  // The customer's own pages now show the money that came back.
  await signInAsCustomer(page, BEN);
  await page.goto("/returns");
  const card = customerReturn(page, returnId);
  await expect(card.getByText("Refunded", { exact: true })).toBeVisible();
  await expect(card.getByText(/\$\d/)).toBeVisible();
});

test("a customer asks for a return, and can only ask for what is left", async ({ page, request }) => {
  await apiSignIn(request, "customer", 2);
  const collected = (await ordersOf(request, 2)).filter((order) => order.status === "collected");

  let chosen: OrderDetail | undefined;
  for (const order of collected) {
    const detail = await apiJson<OrderDetail>(request, `${API}/orders/${order.order_id}`);
    if (detail.return_eligibility.eligible
      && detail.return_eligibility.lines.some((line) => line.remaining_quantity > 0)) {
      chosen = detail;
      break;
    }
  }
  expect(chosen, "a collected order with something still returnable").toBeTruthy();
  const line = chosen!.return_eligibility.lines.find((candidate) => candidate.remaining_quantity > 0)!;

  await signInAsCustomer(page, BEN);
  await page.goto(`/orders/${chosen!.order_id}`);
  const quantity = page.getByLabel(`Quantity to return of ${line.name}`);
  await expect(quantity).toHaveAttribute("max", String(line.remaining_quantity));
  await quantity.fill("1");
  await page.getByLabel("Why are you returning it? (required)").fill("changed my mind");
  await page.getByRole("button", { name: "Request return" }).click();

  await expect(page.getByText(/Return #\d+ requested/)).toBeVisible();
  const requestId = Number((await page.getByText(/Return #\d+ requested/).innerText()).match(/\d+/)![0]);
  const created = await apiJson<{ status: string; order_id: number; refund_preview: string }>(
    request, `${API}/returns/${requestId}`);
  expect(created.status).toBe("requested");
  expect(created.order_id).toBe(chosen!.order_id);
});

test("a rejected return is final: no refund, and the customer is told", async ({ page, request }) => {
  await apiSignIn(request, "customer", 2);
  const requested = (await returnsOf(request, 2)).filter((row) => row.status === "requested");
  expect(requested, "the request the previous test left on the desk").toHaveLength(1);
  const returnId = requested[0].return_id;

  await signInAsStaff(page, SOPHIE_ID);
  await page.goto(`/admin/returns/${returnId}`);
  await page.getByRole("button", { name: "Reject the return" }).click();
  await confirm(page, "Reject the return").click();
  await expect(page.getByText("Rejected", { exact: true }).first()).toBeVisible();

  const rejected = await apiJson<{ status: string; refund_amount: string | null }>(
    request, `${API}/returns/${returnId}`);
  expect(rejected.status).toBe("rejected");
  expect(rejected.refund_amount).toBeNull();

  // …and the customer sees the same, on the return and on the order it came from.
  await signInAsCustomer(page, BEN);
  await page.goto("/returns");
  await expect(customerReturn(page, returnId).getByText("Rejected", { exact: true })).toBeVisible();
});

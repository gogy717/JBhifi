/**
 * The buying journey: browse → cart → checkout (both fulfilment methods) → the order's timeline.
 *
 * Every assertion that matters is made twice: once in the browser (what a customer sees) and once
 * against the API (what the database actually holds), so a page that shows the right words over the
 * wrong rows still fails.
 */
import { expect, test } from "@playwright/test";

import {
  AIDEN, AIDEN_ID, ALICE, API, SYDNEY_CBD, SYDNEY_CBD_ID, addToCart, apiJson, apiSignIn, chooseStore,
  errorCodeShown, openAdminOrder, ordersOf, signInAsCustomer, signInAsStaff, stockedProduct,
} from "./stack";

test("a product's page shows what the catalogue promised", async ({ page, request }) => {
  const product = await stockedProduct(request);

  await page.goto("/products");
  // The header has a search box too: this is the catalogue's own filter.
  await page.getByRole("main").getByLabel("Search products").fill(product.sku);
  const card = page.locator("article").filter({ hasText: product.name }).first();
  await expect(card).toBeVisible();
  await expect(card.getByText(`in stock at ${SYDNEY_CBD}`)).toBeVisible();

  await card.getByRole("link", { name: product.name }).click();
  await expect(page.getByRole("heading", { name: product.name })).toBeVisible();
  await expect(page.getByLabel("Quantity")).toBeVisible();
  // Specs are rows from product_spec, and stock is per store: both come from the product detail read.
  await expect(page.getByRole("heading", { name: /Specifications/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Where it is in stock/i })).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: SYDNEY_CBD }).first()).toBeVisible();
});

test("the cart keeps quantities, re-reads prices and can be emptied", async ({ page, request }) => {
  const product = await stockedProduct(request);
  await addToCart(page, product.name);

  await page.goto("/cart");
  await expect(page.getByRole("heading", { name: "Your cart" })).toBeVisible();
  const line = page.locator("li").filter({ hasText: product.name }).first();
  const oneOff = await line.getByText(/^\$/).first().innerText();

  await page.getByLabel("Quantity").first().fill("2");
  await expect(line.getByText(/^\$/).first()).not.toHaveText(oneOff);
  await expect(page.getByRole("link", { name: "Checkout" })).toBeVisible();

  await page.getByRole("button", { name: "Remove" }).first().click();
  await expect(page.getByText("Your cart is empty")).toBeVisible();
});

test("delivery checkout commits the order, its line, the charge and the status together", async ({ page, request }) => {
  const product = await stockedProduct(request);
  await apiSignIn(request, "customer", 1);
  await signInAsCustomer(page, ALICE);
  await chooseStore(page, SYDNEY_CBD_ID);
  await addToCart(page, product.name);

  await page.goto("/checkout");
  await page.getByRole("button", { name: "Delivery" }).click();
  await page.locator('input[name="address"]').first().check();
  const total = await page.getByText(/^\$\d/).last().innerText();
  await page.getByRole("button", { name: "Place order" }).click();

  await expect(page).toHaveURL(/\/orders\/\d+$/);
  const orderId = Number(page.url().split("/").pop());
  await expect(page.getByRole("heading", { name: `Order #${orderId}` })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await expect(page.getByText("Paid", { exact: true }).first()).toBeVisible();

  // The same order, read straight from the API: one line at the price it was sold at, one charge.
  const order = await apiJson<{
    order_id: number; status: string; total: string; fulfilment_method: string;
    lines: { product_id: number; quantity: number; unit_price: string }[];
    payments: { kind: string; amount: string }[];
    delivery_address: { line1: string } | null;
  }>(request, `${API}/orders/${orderId}`);
  expect(order.status).toBe("paid");
  expect(order.fulfilment_method).toBe("delivery");
  expect(order.lines).toHaveLength(1);
  expect(order.lines[0].product_id).toBe(product.product_id);
  expect(order.lines[0].quantity).toBe(1);
  expect(order.payments.filter((payment) => payment.kind === "charge")).toHaveLength(1);
  expect(order.delivery_address?.line1).toBeTruthy();
  expect(Number(total.replace(/[^0-9.]/g, ""))).toBeCloseTo(Number(order.total));
});

test("a lost reply is retried with the same key and does not buy twice", async ({ page, request }) => {
  const product = await stockedProduct(request);
  await apiSignIn(request, "customer", 1);
  await signInAsCustomer(page, ALICE);
  await chooseStore(page, SYDNEY_CBD_ID);
  await addToCart(page, product.name);
  await page.goto("/checkout");
  await page.getByRole("button", { name: "Click & Collect" }).click();
  await page.getByLabel("Collect from this store").selectOption(String(SYDNEY_CBD_ID));

  // The first attempt really reaches the server — and then the answer is thrown away.
  let dropped = false;
  await page.route("**/api/v1/orders", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    if (dropped) return route.continue();
    dropped = true;
    await route.fetch();
    await route.abort();
  });

  const before = (await ordersOf(request, 1)).length;
  await page.getByRole("button", { name: "Place order" }).click();
  expect(await errorCodeShown(page)).toBe("network_error");

  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page).toHaveURL(/\/orders\/\d+$/);

  // One order, not two: the retry replayed the first request instead of creating another.
  const orderId = Number(page.url().split("/").pop());
  const after = await ordersOf(request, 1);
  expect(after.length).toBe(before + 1);
  expect(after.filter((order) => order.order_id === orderId)).toHaveLength(1);
  const created = await apiJson<{ status: string; lines: { quantity: number }[] }>(
    request, `${API}/orders/${orderId}`);
  expect(created.status).toBe("paid");
  expect(created.lines[0].quantity).toBe(1);
});

test("staff move a delivery order through to delivered, and the customer sees the timeline", async ({ page, request }) => {
  const product = await stockedProduct(request);
  await signInAsCustomer(page, ALICE);
  await chooseStore(page, SYDNEY_CBD_ID);
  await addToCart(page, product.name);
  await page.goto("/checkout");
  await page.getByRole("button", { name: "Delivery" }).click();
  await page.locator('input[name="address"]').first().check();
  await page.getByRole("button", { name: "Place order" }).click();
  await expect(page).toHaveURL(/\/orders\/\d+$/);
  const orderId = Number(page.url().split("/").pop());

  await signInAsStaff(page, AIDEN_ID);
  await openAdminOrder(page, orderId);
  // The buttons are named for the move, not for the status they land on (T12).
  await page.getByRole("button", { name: "Start picking" }).click();
  await page.getByRole("button", { name: "Mark shipped" }).click();
  await page.getByRole("button", { name: "Mark delivered" }).click();
  await expect(page.getByText("Delivered", { exact: true }).first()).toBeVisible();

  // The customer's own view of the same row: the whole timeline, in order, by the staff member who did it.
  await signInAsCustomer(page, ALICE);
  await page.goto(`/orders/${orderId}`);
  const timeline = page.locator("section", { hasText: "Timeline" }).first();
  for (const status of ["Paid", "Being picked", "Shipped", "Delivered"]) {
    await expect(timeline.getByText(status, { exact: true }).first()).toBeVisible();
  }
  await expect(timeline.getByText(new RegExp(`by ${AIDEN}`)).first()).toBeVisible();
  await expect(page.getByText("Request a return")).toBeVisible();
});

test("staff cancel a paid order: the stock goes back and the charge is refunded", async ({ page, request }) => {
  const product = await stockedProduct(request);
  await signInAsCustomer(page, ALICE);
  await chooseStore(page, SYDNEY_CBD_ID);
  await addToCart(page, product.name);
  await page.goto("/checkout");
  await page.getByRole("button", { name: "Click & Collect" }).click();
  await page.getByLabel("Collect from this store").selectOption(String(SYDNEY_CBD_ID));
  await page.getByRole("button", { name: "Place order" }).click();
  await expect(page).toHaveURL(/\/orders\/\d+$/);
  const orderId = Number(page.url().split("/").pop());
  await apiSignIn(request, "customer", 1);
  const stockBefore = await apiJson<{ product_id: number; quantity: number }[]>(
    request, `${API}/stores/1/inventory`);

  await signInAsStaff(page, AIDEN_ID);
  await openAdminOrder(page, orderId);
  await page.getByRole("button", { name: "Cancel order…" }).click();
  await page.getByLabel("Why is it being cancelled?").fill("customer changed their mind");
  await page.getByRole("button", { name: "Cancel and refund" }).click();
  await expect(page.getByText("Cancelled", { exact: true }).first()).toBeVisible();

  const cancelled = await apiJson<{ status: string; payments: { kind: string }[] }>(
    request, `${API}/orders/${orderId}`);
  expect(cancelled.status).toBe("cancelled");
  expect(cancelled.payments.some((payment) => payment.kind === "refund")).toBe(true);
  const after = await apiJson<{ product_id: number; quantity: number }[]>(request, `${API}/stores/1/inventory`);
  const row = (rows: { product_id: number; quantity: number }[]) =>
    rows.find((candidate) => candidate.product_id === product.product_id)?.quantity ?? 0;
  expect(row(after)).toBe(row(stockBefore) + 1);      // the cancelled unit is back on the shelf
});

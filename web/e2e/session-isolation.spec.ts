/**
 * Who a page is allowed to show (T01, review risk 3): a guest, a customer, and a staff member whose
 * session does not shop. Nothing here changes data — it is all about what the pages will display.
 */
import { expect, test } from "@playwright/test";

import {
  AIDEN_ID, ALICE, API, BEN, apiJson, apiSignIn, errorCodeShown, signInAsCustomer, signInAsStaff,
} from "./stack";

test("a guest is asked to sign in and is shown nobody's data", async ({ page }) => {
  await page.goto("/orders");
  await expect(page.getByText(/Sign in \(demo\)/).first()).toBeVisible();

  await page.goto("/account");
  await expect(page.getByText(/Sign in \(demo\) on the/)).toBeVisible();

  await page.goto("/checkout");
  await expect(page.getByText("Checkout needs a customer.")).toBeVisible();
});

test("switching customer changes the records, and another customer's order is not readable", async ({ page, request }) => {
  await apiSignIn(request, "customer", 1);                      // Alice Morgan
  const aliceOrder = (await apiJson<{ order_id: number }[]>(request, `${API}/customers/1/orders`))[0];
  expect(aliceOrder, "Alice has at least one seeded order").toBeTruthy();

  await signInAsCustomer(page, ALICE);
  await page.goto("/orders");
  await expect(page.getByText(`Order #${aliceOrder.order_id}`).first()).toBeVisible();

  // Switch to Ben: the list must belong to him, not to the customer who was there a moment ago.
  await page.getByLabel("Signed in as").selectOption({ label: BEN });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Hi, Ben" })).toBeVisible();
  await page.goto("/orders");
  await expect(page.getByText(`Order #${aliceOrder.order_id}`)).toHaveCount(0);

  // And Alice's order, by URL, is not Ben's to read: the API answers "not found", which is also what an
  // order that does not exist would say, so ids cannot be probed.
  await page.goto(`/orders/${aliceOrder.order_id}`);
  expect(await errorCodeShown(page)).toBe("not_found");
});

test("a staff session on the storefront is a guest, not a customer", async ({ page }) => {
  await signInAsStaff(page, AIDEN_ID);

  // The storefront declares who *it* acts as: a customer. A staff cookie is signed out, so no customer
  // page can show a staff member a customer's rows.
  await page.goto("/orders");
  await expect(page.getByText(/Sign in \(demo\)/).first()).toBeVisible();
  await page.goto("/account");
  await expect(page.getByText(/Sign in \(demo\) on the/)).toBeVisible();
});

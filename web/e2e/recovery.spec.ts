/**
 * The refusals a customer can meet, shown in the browser (T18): the empty store, a product that is
 * retired between the cart and the checkout, and an address that no longer accepts deliveries.
 *
 * Each test arranges the awkward state the way the application itself would — through the API, as the
 * person entitled to do it — and then checks what the page says.
 */
import { expect, test } from "@playwright/test";

import {
  ALICE, API, API_ORIGIN, BONDI_JUNCTION_ID, EMPTY_AT_SYDNEY, OLIVIA_MANAGER, SYDNEY_CBD_ID,
  TOM, addToCart, apiSignIn, chooseStore, errorCodeShown, ordersOf, productBySku, signInAsCustomer,
  stockedProduct,
} from "./stack";

test("the store with nothing left refuses the order and says which rule stopped it", async ({ page, request }) => {
  await apiSignIn(request, "customer", 1);
  const before = (await ordersOf(request, 1)).length;
  await signInAsCustomer(page, ALICE);
  // The seeded example emptied LG-43UT8050 at Sydney CBD only, so add it while another store is chosen…
  const empty = await productBySku(request, EMPTY_AT_SYDNEY);
  await chooseStore(page, BONDI_JUNCTION_ID);
  await addToCart(page, empty.name);
  // …then ask for it at Sydney CBD, where the shelf is empty.
  await chooseStore(page, SYDNEY_CBD_ID);

  await page.goto("/checkout");
  await page.getByRole("button", { name: "Click & Collect" }).click();
  await page.getByLabel("Collect from this store").selectOption(String(SYDNEY_CBD_ID));
  await page.getByRole("button", { name: "Place order" }).click();

  expect(await errorCodeShown(page)).toBe("out_of_stock");
  await expect(page.getByText("Nothing was charged and your cart is unchanged.")).toBeVisible();
  // Nothing was written: the customer still has exactly the orders they started with.
  expect((await ordersOf(request, 1)).length).toBe(before);
});

test("a product retired after it went in the cart blocks the checkout until it is removed", async ({ page, request }) => {
  const product = await stockedProduct(request);
  await addToCart(page, product.name);

  // A store manager retires the product (BR: the catalogue is theirs to maintain).
  await apiSignIn(request, "staff", OLIVIA_MANAGER);           // Olivia Nguyen, store 1's manager
  const retired = await request.patch(`${API_ORIGIN}${API}/products/${product.product_id}`,
    { data: { is_active: false } });
  expect(retired.ok()).toBeTruthy();

  await page.goto("/cart");
  await expect(page.getByText("Retired — remove it to continue.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Checkout" })).toHaveAttribute("aria-disabled", "true");

  await page.getByRole("button", { name: "Remove" }).first().click();
  await expect(page.getByText("Your cart is empty")).toBeVisible();
});

test("an address retired between the cart and the checkout cannot be delivered to", async ({ page, request }) => {
  const product = await stockedProduct(request);
  await signInAsCustomer(page, TOM);
  await chooseStore(page, SYDNEY_CBD_ID);
  await addToCart(page, product.name);

  await page.goto("/checkout");
  await page.getByRole("button", { name: "Delivery" }).click();
  await expect(page.locator('input[name="address"]').first()).toBeVisible();

  // Tom retires his only address in "My account"; this request context is his session, not the browser's.
  await apiSignIn(request, "customer", 4);
  const current = await request.get(`${API_ORIGIN}${API}/customers/4`);
  const addresses = (await current.json()) as { addresses: { address_no: number; is_active: boolean }[] };
  const active = addresses.addresses.find((address) => address.is_active)!;
  const retired = await request.patch(
    `${API_ORIGIN}${API}/customers/4/addresses/${active.address_no}`, { data: { is_active: false } });
  expect(retired.ok()).toBeTruthy();

  await page.reload();
  // A reload starts the page in its default mode, so the delivery form has to be chosen again.
  await page.getByRole("button", { name: "Delivery" }).click();
  await expect(page.getByText("You have no current address.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Add one in My account →" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Place order" })).toBeDisabled();
});

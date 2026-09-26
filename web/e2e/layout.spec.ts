/**
 * Nothing a customer can reach is still a placeholder, and the pages survive a narrow screen (T18).
 *
 * The reserved pages of Phase 1 carried their own plan copy ("Reserved — not built yet", "API it needs",
 * "Slice A — …"). Once a page is built that copy has to be gone, and this is the check that keeps it
 * gone: it reads every customer route, and the admin's own navigation, at a phone width.
 */
import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 } });

const CUSTOMER_ROUTES = [
  { path: "/", heading: /JB Hi-Fi|Hi, / },
  { path: "/products", heading: "Shop all products" },
  { path: "/cart", heading: "Your cart" },
  { path: "/checkout", heading: "Checkout" },
  { path: "/orders", heading: "My orders" },
  { path: "/returns", heading: "My returns" },
  { path: "/stores", heading: "Stores" },
  { path: "/account", heading: "My account" },
];

test("no customer route is still reserved, on a phone-sized screen", async ({ page }) => {
  for (const route of CUSTOMER_ROUTES) {
    await page.goto(route.path);
    await expect(page.getByRole("heading", { name: route.heading }).first()).toBeVisible();
    await expect(page.getByText("Reserved — not built yet")).toHaveCount(0);
    await expect(page.getByText("API it needs")).toHaveCount(0);
    await expect(page.getByText(/plan §10/)).toHaveCount(0);
    await expect(page.getByText(/fastapi dev app\/main\.py/)).toHaveCount(0);
  }
});

test("a product page is a page, not a promise", async ({ page, request }) => {
  const response = await request.get(`http://127.0.0.1:${process.env.E2E_API_PORT ?? 8100}/api/v1/products`);
  expect(response.ok()).toBeTruthy();
  const [product] = (await response.json()) as { product_id: number; name: string }[];

  await page.goto(`/products/${product.product_id}`);
  await expect(page.getByRole("heading", { name: product.name })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add to cart" })).toBeVisible();
  await expect(page.getByText("Reserved — not built yet")).toHaveCount(0);
});

test("the admin keeps its whole navigation at a phone width", async ({ page }) => {
  await page.goto("/admin/orders");
  for (const label of ["Inventory", "Orders", "Returns", "Products", "Promotions"]) {
    await expect(page.getByRole("link", { name: new RegExp(label) }).first()).toBeVisible();
  }
  await page.goto("/admin/returns");
  await expect(page.getByRole("heading", { name: "Returns desk" })).toBeVisible();
});

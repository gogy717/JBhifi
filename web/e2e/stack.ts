import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** The stack the config starts: the API the browser talks to (through Next's proxy) and its database. */
export const API_ORIGIN = `http://127.0.0.1:${process.env.E2E_API_PORT ?? 8100}`;
export const API = "/api/v1";

// What `sql/10_seed_reference.sql` puts there, so the journeys can name things instead of guessing.
export const SYDNEY_CBD = "Sydney CBD";
export const BONDI_JUNCTION = "Bondi Junction";
export const MELBOURNE_CENTRAL = "Melbourne Central";
export const SYDNEY_CBD_ID = 1;                // store ids are the seed's, and stable for a fresh database
export const BONDI_JUNCTION_ID = 2;
export const MELBOURNE_CENTRAL_ID = 5;
export const ALICE = "Alice Morgan";
export const BEN = "Ben Okafor";
export const TOM = "Tom Fraser";
export const AIDEN = "Aiden Chen";              // store staff at Sydney CBD
export const SOPHIE = "Sophie Brown";           // store staff at Melbourne Central
export const EMPTY_AT_SYDNEY = "LG-43UT8050";   // the seeded out-of-stock example

// Staff ids from `sql/10_seed_reference.sql`; the picker's option text carries a "(manager)" suffix, so
// the id is the stable way to choose someone.
export const OLIVIA_MANAGER = 1;                // manager of store 1
export const SOPHIE_ID = 5;                     // store staff at Melbourne Central
export const AIDEN_ID = 14;                     // store staff at Sydney CBD
export const SAMUEL_WAREHOUSE = 38;             // store staff at the warehouse

export type InventoryRow = {
  product_id: number; sku: string; name: string; quantity: number; is_active: boolean;
};

export type OrderSummary = {
  order_id: number; status: string; total: string; fulfilment_method: string; line_count: number;
};

export type ReturnSummary = {
  return_id: number; order_id: number; status: string; refund_amount: string | null;
};

// ---------------------------------------------------------------- browsing the storefront

/** Sign in (demo) through the header picker, and wait until the storefront has accepted the session. */
export async function signInAsCustomer(page: Page, name: string) {
  await page.goto("/");
  await page.getByLabel("Signed in as").selectOption({ label: name });
  await expect(page.getByRole("heading", { name: `Hi, ${name.split(" ")[0]}` })).toBeVisible();
}

/** "My store" is the store stock and Click & Collect are judged against. Chosen by id: the picker is in
 *  the header on every page, so it can be set from wherever the journey happens to be. */
export async function chooseStore(page: Page, storeId: number) {
  const picker = page.getByLabel("My store");
  await picker.selectOption(String(storeId));
  await expect(picker).toHaveValue(String(storeId));
}

/** A product with real stock at a store, so a journey never depends on a hand-picked row. */
export async function stockedProduct(request: APIRequestContext, storeId = 1, atLeast = 3) {
  const response = await request.get(`${API_ORIGIN}${API}/stores/${storeId}/inventory`);
  expect(response.ok()).toBeTruthy();
  const rows = (await response.json()) as InventoryRow[];
  const row = rows.find((candidate) => candidate.is_active && candidate.quantity >= atLeast);
  expect(row, `a product with at least ${atLeast} at store ${storeId}`).toBeTruthy();
  return row!;
}

/** One product by SKU — the catalogue cards show a name, not the SKU, so journeys need the name. */
export async function productBySku(request: APIRequestContext, sku: string) {
  const response = await request.get(`${API_ORIGIN}${API}/products`, { params: { q: sku } });
  expect(response.ok()).toBeTruthy();
  const rows = (await response.json()) as { product_id: number; sku: string; name: string }[];
  const row = rows.find((candidate) => candidate.sku === sku);
  expect(row, `a product with SKU ${sku}`).toBeTruthy();
  return row!;
}

/** Add one from the catalogue: the card's own button, so no product page is involved. */
export async function addToCart(page: Page, productName: string) {
  await page.goto("/products");
  const card = page.locator("article").filter({ hasText: productName }).first();
  await card.getByRole("button", { name: "Add to cart" }).click();
  await expect(page.getByRole("status")).toContainText(productName);
}

// ---------------------------------------------------------------- the admin app

export async function signInAsStaff(page: Page, staffId: number) {
  await page.goto("/admin/orders");
  await page.getByLabel("Demo staff sign-in").selectOption(String(staffId));
  // The bar says so when somebody is acting; when it does, the session the API issued is this staff
  // member's, and the queue below is theirs to read.
  await expect(page.getByText("Not signed in — the API will refuse every change until you pick someone."))
    .toHaveCount(0);
}

/** Open an order in the staff queue and hand back the page. */
export async function openAdminOrder(page: Page, orderId: number) {
  await page.goto(`/admin/orders/${orderId}`);
  await expect(page.getByRole("heading", { name: `Order #${orderId}` })).toBeVisible();
}

// ---------------------------------------------------------------- the API, for setting up and checking

/** Make this request context act as a customer or staff member (its own cookie jar). */
export async function apiSignIn(request: APIRequestContext, kind: "customer" | "staff", id: number) {
  const response = await request.post(`${API_ORIGIN}${API}/session`, { data: { kind, id } });
  expect(response.ok(), `sign in as ${kind} ${id}`).toBeTruthy();
}

export async function apiJson<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(`${API_ORIGIN}${path}`);
  expect(response.ok(), `GET ${path}`).toBeTruthy();
  return (await response.json()) as T;
}

export const ordersOf = (request: APIRequestContext, customerId: number) =>
  apiJson<OrderSummary[]>(request, `${API}/customers/${customerId}/orders`);

export const returnsOf = (request: APIRequestContext, customerId: number) =>
  apiJson<ReturnSummary[]>(request, `${API}/customers/${customerId}/returns`);

/** The code the page is showing in its error box — for a database refusal, the constraint's name. */
export async function errorCodeShown(page: Page) {
  const alert = page.getByRole("alert").first();
  await expect(alert).toBeVisible();
  return (await alert.locator("code").first().innerText()).trim();
}

// The customer routes, and what each of them is for. Every route listed here is built; the entries are
// kept because they are also the catalogue of which requirement (R#), rule (BR#) and transaction (T#)
// each screen is answerable for — useful when a reviewer asks "where is R3 met?".
// R# and BR# refer to the recovered requirements in doc/requirements.md, T# to the plan's transactions.

export type Endpoint = { method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE"; path: string; exists: boolean };

export type ShopPage = {
  href: string;
  title: string;
  summary: string;
  features: string[];
  requirements: string[];
  rules: string[];
  transaction?: string;
  api: Endpoint[];
  slice: "A — Catalogue & stock" | "B — Orders & checkout" | "C — Returns, staff & reporting";
};

export const REQUIREMENTS: Record<string, string> = {
  R1: "Browse by category and brand, search, filter by price",
  R2: "Current price, including any active promotion",
  R3: "A product's stock at each store",
  R4: "Place an order for delivery or Click & Collect",
  R5: "View orders with a status timeline",
  R6: "Request returns for completed orders",
  R11: "Every status change is auditable",
};

export const RULES: Record<string, string> = {
  BR01: "Customer email is unique and well-formed",
  BR03: "Stock never goes negative",
  BR06: "Delivery has an address; Click & Collect is at a retail store",
  BR07: "Line quantity > 0; a product appears once per order",
  BR08: "A line keeps the price it was sold at",
  BR09: "Status follows the allowed transitions, and is logged",
  BR10: "A retried checkout creates at most one order",
  BR11: "Returns only for completed orders, within 30 days",
  BR12: "Returned quantity ≤ purchased quantity",
  BR13: "Return lines come from the returned order",
  BR14: "Refunds never exceed what was charged",
  BR15: "Promotions: below base price, never overlapping",
  BR16: "Addresses are never edited, only replaced",
  BR17: "A delivery address belongs to the customer",
};

export const TRANSACTIONS: Record<string, string> = {
  T1: "Checkout: order, stock, payment and status in one transaction",
  T2: "Process a return: restock and refund in one transaction",
};

const get = (path: string, exists: boolean): Endpoint => ({ method: "GET", path, exists });

export const SHOP_PAGES = {
  catalogue: {
    href: "/products",
    title: "Shop all products",
    summary: "Browse the catalogue by category and brand, search it, and filter by price.",
    features: [
      "Search box and category links already arrive here as ?q= and ?category=",
      "Filters: category (with its subcategories), brand, price range",
      "Each result shows the current price (sale price while a promotion runs) and stock at your store",
    ],
    requirements: ["R1", "R2", "R3"],
    rules: ["BR15"],
    api: [
      get("/api/v1/products?q=&category_id=&brand_id=", true),
      get("/api/v1/products?min_price=&max_price=", false),
      get("/api/v1/stores/{store_id}/inventory", true),
    ],
    slice: "A — Catalogue & stock",
  },
  product: {
    href: "/products/[id]",
    title: "Product",
    summary: "One product: its price, specs, and where it is in stock.",
    features: [
      "Current price, with the base price struck through during a promotion",
      "Specifications (key–value rows from product_spec)",
      "Stock at every store, your store first; add to cart",
    ],
    requirements: ["R2", "R3"],
    rules: ["BR03", "BR15"],
    api: [get("/api/v1/products/{product_id}", true)],
    slice: "A — Catalogue & stock",
  },
  cart: {
    href: "/cart",
    title: "Cart",
    summary: "The products you're about to buy, kept in the browser until checkout.",
    features: [
      "Change quantities, remove items; prices refreshed from the current-price view",
      "Warns when your store has less stock than you want (checkout re-checks in the database)",
    ],
    requirements: ["R2", "R4"],
    rules: ["BR07"],
    api: [get("/api/v1/stores/{store_id}/inventory", true)],
    slice: "A — Catalogue & stock",
  },
  checkout: {
    href: "/checkout",
    title: "Checkout",
    summary: "Pay (simulated) for delivery to one of your addresses, or Click & Collect at a retail store.",
    features: [
      "Choose delivery (one of your current addresses) or Click & Collect (a retail store, never the warehouse)",
      "One POST = one transaction: order, lines at today's prices, stock taken, charge recorded, status → paid",
      "Retrying with the same Idempotency-Key returns the same order instead of a second one",
      "Out of stock at the last moment: nothing is saved, and the page says which item and store",
    ],
    requirements: ["R4", "R11"],
    rules: ["BR03", "BR06", "BR07", "BR08", "BR09", "BR10", "BR17"],
    transaction: "T1",
    api: [{ method: "POST", path: "/api/v1/orders  (header: Idempotency-Key)", exists: false }],
    slice: "B — Orders & checkout",
  },
  orders: {
    href: "/orders",
    title: "My orders",
    summary: "Your orders, newest first, with their totals and where each one is up to.",
    features: [
      "Order total from the v_order_total view; latest status",
      "Click & Collect orders that are ready are highlighted",
    ],
    requirements: ["R5"],
    rules: ["BR09"],
    api: [get("/api/v1/customers/{customer_id}/orders", false)],
    slice: "B — Orders & checkout",
  },
  order: {
    href: "/orders/[id]",
    title: "Order",
    summary: "One order: its lines, its status timeline, and returning items from it.",
    features: [
      "Timeline from order_status_history: every status change, when, and by whom",
      "Request a return for delivered or collected orders, within 30 days",
    ],
    requirements: ["R5", "R6", "R11"],
    rules: ["BR09", "BR11", "BR12", "BR13"],
    api: [
      get("/api/v1/orders/{order_id}", false),
      { method: "POST", path: "/api/v1/orders/{order_id}/returns  (header: Idempotency-Key)", exists: false },
    ],
    slice: "B — Orders & checkout",
  },
  returns: {
    href: "/returns",
    title: "My returns",
    summary: "Returns you have requested, and where each one is up to: requested → received → refunded.",
    features: [
      "Status of each return and the refund amount once refunded",
      "Rejected returns stay visible (rejected is final)",
    ],
    requirements: ["R6"],
    rules: ["BR11", "BR12", "BR14"],
    transaction: "T2",
    api: [get("/api/v1/customers/{customer_id}/returns", false)],
    slice: "C — Returns, staff & reporting",
  },
  stores: {
    href: "/stores",
    title: "Stores",
    summary: "Every store, by state, and which of them has a product in stock.",
    features: [
      "Stores by state; pick your store for Click & Collect and stock checks",
      "“Who has it?”: a product's stock at every store (the home page already shows stores near you)",
    ],
    requirements: ["R3"],
    rules: ["BR06"],
    api: [get("/api/v1/stores", true), get("/api/v1/products/{product_id}", true)],
    slice: "A — Catalogue & stock",
  },
  account: {
    href: "/account",
    title: "My account",
    summary: "Your details and delivery addresses.",
    features: [
      "Addresses: add a new one or retire an old one — an address is never edited, because orders point to it",
      "Past addresses stay listed as inactive",
    ],
    requirements: [],
    rules: ["BR01", "BR16", "BR17"],
    api: [
      get("/api/v1/customers/{customer_id}", true),
      { method: "POST", path: "/api/v1/customers/{customer_id}/addresses", exists: false },
      { method: "PATCH", path: "/api/v1/customers/{customer_id}/addresses/{address_no}  (is_active: false only)", exists: false },
    ],
    slice: "B — Orders & checkout",
  },
} satisfies Record<string, ShopPage>;

export type ShopPageId = keyof typeof SHOP_PAGES;

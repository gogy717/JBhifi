/**
 * The browser cart: product ids and quantities only.
 *
 * It reserves nothing and holds no prices — checkout always re-reads the current price from the database, and
 * the totals shown here are only what the customer reviewed. All arithmetic is in integer cents, so 19.95 × 3
 * is exactly 59.85 and never 59.849999999999994.
 */

export const CART_VERSION = 1;
export const CART_STORAGE_KEY = "jb.shop.cart";
export const MAX_QUANTITY = 99;

export type CartItem = { product_id: number; quantity: number };
export type CartState = { version: typeof CART_VERSION; items: CartItem[] };

export const EMPTY_CART: CartState = { version: CART_VERSION, items: [] };

function validQuantity(quantity: unknown): quantity is number {
  return typeof quantity === "number" && Number.isInteger(quantity) && quantity > 0 && quantity <= MAX_QUANTITY;
}

function validItem(item: unknown): item is CartItem {
  const candidate = item as CartItem | null;
  return candidate !== null && typeof candidate === "object"
    && Number.isInteger(candidate.product_id) && candidate.product_id > 0
    && validQuantity(candidate.quantity);
}

/** Read a cart from stored text. Anything unrecognised (older version, hand-edited, corrupt) is dropped. */
export function readCart(raw: string | null): CartState {
  if (!raw) return EMPTY_CART;
  try {
    const parsed = JSON.parse(raw) as Partial<CartState> | null;
    if (!parsed || parsed.version !== CART_VERSION || !Array.isArray(parsed.items)) return EMPTY_CART;
    const items = parsed.items.filter(validItem).map((item) => ({
      product_id: item.product_id,
      quantity: item.quantity,
    }));
    // A product listed twice would be ambiguous, so the first occurrence wins.
    const seen = new Set<number>();
    return {
      version: CART_VERSION,
      items: items.filter((item) => !seen.has(item.product_id) && seen.add(item.product_id)),
    };
  } catch {
    return EMPTY_CART;
  }
}

export function writeCart(state: CartState): string {
  return JSON.stringify(state);
}

function normalise(quantity: number): number {
  return Math.min(Math.max(Math.trunc(quantity), 1), MAX_QUANTITY);
}

/** Add a product, merging with a line that is already there rather than adding a second one. */
export function addItem(items: CartItem[], product_id: number, quantity = 1): CartItem[] {
  const existing = items.find((item) => item.product_id === product_id);
  if (!existing) return [...items, { product_id, quantity: normalise(quantity) }];
  return items.map((item) => item.product_id === product_id
    ? { ...item, quantity: normalise(item.quantity + quantity) }
    : item);
}

export function setQuantity(items: CartItem[], product_id: number, quantity: number): CartItem[] {
  if (quantity <= 0) return removeItem(items, product_id);
  return items.map((item) => item.product_id === product_id
    ? { ...item, quantity: normalise(quantity) }
    : item);
}

export function removeItem(items: CartItem[], product_id: number): CartItem[] {
  return items.filter((item) => item.product_id !== product_id);
}

/** Money as integer cents. `toCents("19.95")` is 1995, never 1994.9999999999998. */
export function toCents(decimal: string): number {
  const match = /^(-?)(\d*)(?:\.(\d*))?$/.exec(decimal.trim());
  if (!match) return 0;
  const [, sign, whole = "0", fraction = ""] = match;
  const cents = Number(whole) * 100 + Number((fraction + "00").slice(0, 2));
  return sign === "-" ? -cents : cents;
}

export function fromCents(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const absolute = Math.abs(cents);
  return `${sign}${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, "0")}`;
}

/** One line's value, in cents, from the price the API reported. */
export function lineTotalCents(price: string, quantity: number): number {
  return toCents(price) * quantity;
}

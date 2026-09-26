"use client";

import { createContext, type ReactNode, useContext, useMemo, useSyncExternalStore } from "react";

import { addItem as addToItems, CART_STORAGE_KEY, type CartItem, type CartState, EMPTY_CART, readCart,
  removeItem as removeFromItems, setQuantity as setQuantityIn, writeCart } from "./cart";

/**
 * The cart, kept in this browser and read through `useSyncExternalStore` — so the server render and the
 * hydration render agree on an empty cart, and the browser's value appears immediately afterwards with no
 * effect-and-setState dance. It survives a customer switch by design (they might add items before signing
 * in) and holds nothing identity-specific: no prices, no customer, no order.
 */

const cartListeners = new Set<() => void>();
let memoryRaw: string | null = null;             // used when localStorage is blocked
let cachedRaw: string | null | undefined;        // `undefined` means "not read yet"
let cachedState: CartState = EMPTY_CART;

function subscribe(listener: () => void) {
  cartListeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    cartListeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function rawCart(): string | null {
  try {
    return window.localStorage.getItem(CART_STORAGE_KEY);
  } catch {
    return memoryRaw;
  }
}

/** useSyncExternalStore needs a stable reference while the stored text has not changed. */
function getSnapshot(): CartState {
  const raw = rawCart();
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cachedState = readCart(raw);
  }
  return cachedState;
}

function getServerSnapshot(): CartState {
  return EMPTY_CART;
}

function store(next: CartState) {
  const raw = writeCart(next);
  memoryRaw = raw;
  try {
    window.localStorage.setItem(CART_STORAGE_KEY, raw);
  } catch {
    // The cart still works for this page view.
  }
  cachedRaw = undefined;                          // force a re-read on the next snapshot
  cartListeners.forEach((listener) => listener());
}

type CartValue = {
  items: CartItem[];
  /** False only during the server render and the hydration render. */
  ready: boolean;
  count: number;
  addItem: (product_id: number, quantity?: number) => void;
  setQuantity: (product_id: number, quantity: number) => void;
  removeItem: (product_id: number) => void;
  /** After a checkout, take out only what was submitted: anything added meanwhile stays. */
  removeSubmitted: (submitted: CartItem[]) => void;
  clear: () => void;
};

const CartContext = createContext<CartValue | null>(null);

export function useCart(): CartValue {
  const value = useContext(CartContext);
  if (!value) throw new Error("useCart() must be used inside <CartProvider>");
  return value;
}

export function CartProvider({ children }: { children: ReactNode }) {
  const state = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  // The browser has taken over once this flips; `false` only on the server and the hydration render.
  const ready = useSyncExternalStore(subscribe, () => true, () => false);

  const value = useMemo<CartValue>(() => ({
    items: state.items,
    ready,
    count: state.items.reduce((total, item) => total + item.quantity, 0),
    addItem: (product_id, quantity = 1) => store({ version: 1, items: addToItems(state.items, product_id, quantity) }),
    setQuantity: (product_id, quantity) => store({ version: 1, items: setQuantityIn(state.items, product_id, quantity) }),
    removeItem: (product_id) => store({ version: 1, items: removeFromItems(state.items, product_id) }),
    removeSubmitted: (submitted) => store({
      version: 1,
      items: submitted.reduce(
        (items, item) => setQuantityIn(items, item.product_id,
          (items.find((current) => current.product_id === item.product_id)?.quantity ?? 0) - item.quantity),
        state.items,
      ),
    }),
    clear: () => store({ version: 1, items: [] }),
  }), [state.items, ready]);

  return <CartContext value={value}>{children}</CartContext>;
}

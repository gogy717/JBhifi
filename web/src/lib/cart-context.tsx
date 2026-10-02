"use client";

import { createContext, type ReactNode, useContext, useMemo, useSyncExternalStore } from "react";

import { readStored, subscribeStored, writeStored } from "./browser-storage";
import {
  addItem as addToItems, CART_STORAGE_KEY, CART_VERSION, type CartItem, type CartState, EMPTY_CART, readCart,
  removeItem as removeFromItems, setQuantity as setQuantityIn, writeCart,
} from "./cart";

/**
 * The cart, kept in this browser (lib/browser-storage.ts). It holds no prices and nothing about who is signed
 * in, so it is kept across signing in and out: a guest fills a cart, then signs in at checkout.
 */

// useSyncExternalStore needs the same object back while the stored text is unchanged.
let cached: { raw: string | null; state: CartState } = { raw: null, state: EMPTY_CART };

function getSnapshot(): CartState {
  const raw = readStored(CART_STORAGE_KEY);
  if (raw !== cached.raw) cached = { raw, state: readCart(raw) };
  return cached.state;
}

const getServerSnapshot = () => EMPTY_CART;

// Each change starts from the stored cart, not from the last render, so two changes in one click both count.
function change(update: (items: CartItem[]) => CartItem[]) {
  writeStored(CART_STORAGE_KEY, writeCart({ version: CART_VERSION, items: update(getSnapshot().items) }));
}

const actions = {
  addItem: (product_id: number, quantity = 1) => change((items) => addToItems(items, product_id, quantity)),
  setQuantity: (product_id: number, quantity: number) =>
    change((items) => setQuantityIn(items, product_id, quantity)),
  removeItem: (product_id: number) => change((items) => removeFromItems(items, product_id)),
  /** After a checkout, take out only what was submitted: anything added meanwhile stays. */
  removeSubmitted: (submitted: CartItem[]) => change((items) => submitted.reduce(
    (remaining, sent) => setQuantityIn(remaining, sent.product_id,
      (remaining.find((line) => line.product_id === sent.product_id)?.quantity ?? 0) - sent.quantity),
    items)),
  clear: () => change(() => []),
};

type CartValue = typeof actions & {
  items: CartItem[];
  /** False during the server render and the hydration render, when the stored cart can't be read yet. */
  ready: boolean;
  /** Units in the cart, for the header. */
  count: number;
};

const CartContext = createContext<CartValue | null>(null);

export function useCart(): CartValue {
  const value = useContext(CartContext);
  if (!value) throw new Error("useCart() must be used inside <CartProvider>");
  return value;
}

export function CartProvider({ children }: { children: ReactNode }) {
  const { items } = useSyncExternalStore(subscribeStored, getSnapshot, getServerSnapshot);
  const ready = useSyncExternalStore(subscribeStored, () => true, () => false);
  const value = useMemo<CartValue>(() => ({
    ...actions,
    items,
    ready,
    count: items.reduce((total, item) => total + item.quantity, 0),
  }), [items, ready]);
  return <CartContext value={value}>{children}</CartContext>;
}

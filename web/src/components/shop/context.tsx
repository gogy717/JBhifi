"use client";

import { createContext, type ReactNode, useContext, useSyncExternalStore } from "react";

import { type ApiError, api, call, type Category, type CustomerDetail, type Store } from "@/lib/api/client";
import { type MeState, useMe } from "@/lib/me";
import { useLoad } from "@/lib/use-load";

// ---------------------------------------------------------------- per-viewer choices
// Which store is "mine" is a convenience for this browser only, so it lives in localStorage. It is read
// through useSyncExternalStore: the server render and hydration see nothing chosen, then the browser's
// value — no effect-and-setState dance. If storage is blocked (private window), a choice still works in
// memory until the page reloads. (Who is signed in is Clerk's business: see useMe.)

const listeners = new Set<() => void>();
const memory = new Map<string, string | null>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return memory.get(key) ?? null;
  }
}

function writeStored(key: string, value: string | null) {
  memory.set(key, value);
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // storage blocked: the in-memory value above still applies
  }
  listeners.forEach((listener) => listener());
}

function useStoredId(key: string): [number | undefined, (id: number | undefined) => void] {
  const raw = useSyncExternalStore(subscribe, () => readStored(key), () => null);
  const id = raw === null ? NaN : Number(raw);
  return [Number.isInteger(id) ? id : undefined, (next) => writeStored(key, next === undefined ? null : String(next))];
}

// ---------------------------------------------------------------- shop context

type Shop = {
  /** Who is signed in, as the API sees them (a Clerk sign-in, mapped to our data by GET /me). */
  session: MeState;
  /** The signed-in customer, with addresses; undefined for a guest, for staff, or while loading. */
  customer?: CustomerDetail;
  /** Still finding out who is signed in, or their details haven't arrived yet. */
  customerLoading: boolean;
  /** Stores a customer can shop at: retail only — the warehouse doesn't do Click & Collect (BR06). */
  retailStores: Store[];
  /** "My store": the one chosen, else the first in the customer's state, else the first store.
   *  undefined while stores (or the signed-in customer, whose state decides it) are still loading. */
  store?: Store;
  /** undefined goes back to the default (nearest store). */
  setStoreId: (id: number | undefined) => void;
  /** State of the customer's current address, used for "stores near you". */
  homeState?: string;
  categories: Category[];
  /** Who-am-I, stores or categories failed to load (e.g. the API isn't running). */
  loadError?: ApiError;
  /** Try those loads again. */
  reload: () => void;
};

const ShopContext = createContext<Shop | null>(null);

export function useShop(): Shop {
  const shop = useContext(ShopContext);
  if (!shop) throw new Error("useShop() must be used inside <ShopProvider>");
  return shop;
}

export function ShopProvider({ children }: { children: ReactNode }) {
  const session = useMe();
  const [storeId, setStoreId] = useStoredId("jb.shop.storeId");
  const customerId = session.status === "signed-in" && session.me.kind === "customer" ? session.me.id : undefined;

  const stores = useLoad("stores", () => call(api.GET("/api/v1/stores")));
  const categories = useLoad("categories", () => call(api.GET("/api/v1/categories")));
  const detail = useLoad(`customer:${customerId}`, () =>
    customerId === undefined
      ? Promise.resolve(undefined)
      : call(api.GET("/api/v1/customers/{customer_id}", { params: { path: { customer_id: customerId } } })));

  // While another customer loads, don't show the previous one's details under the new name.
  const customer = detail.data?.customer_id === customerId ? detail.data : undefined;
  const homeState = customer?.addresses.find((a) => a.is_active)?.state;
  const retailStores = (stores.data ?? []).filter((s) => s.store_type === "retail");
  const customerLoading = session.status === "loading" || (customerId !== undefined && !customer && !detail.error);
  // Don't guess a store from the first one while the customer's state is still on its way.
  const store = retailStores.find((s) => s.store_id === storeId)
    ?? (customerLoading ? undefined : retailStores.find((s) => s.state === homeState) ?? retailStores[0]);

  const shop: Shop = {
    session,
    customer,
    customerLoading,
    retailStores,
    store,
    setStoreId,
    homeState,
    categories: categories.data ?? [],
    loadError: (session.status === "error" ? session.error : undefined) ?? stores.error ?? categories.error,
    reload: () => {
      if (session.status === "error") session.retry();
      stores.reload();
      categories.reload();
    },
  };
  return <ShopContext value={shop}>{children}</ShopContext>;
}

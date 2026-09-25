"use client";

import { createContext, type ReactNode, useContext, useSyncExternalStore } from "react";

import { type ApiError, api, call, type Category, type Customer, type CustomerDetail, type Store } from "@/lib/api/client";
import { useLoad } from "@/lib/use-load";

// ---------------------------------------------------------------- per-viewer choices
// Who is "signed in" (demo) and which store is "mine" are conveniences for this browser only, so they live
// in localStorage. They are read through useSyncExternalStore: the server render and hydration see nothing
// chosen, then the browser's value — no effect-and-setState dance. If storage is blocked (private window),
// a choice still works in memory until the page reloads.

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
  customers: Customer[];
  /** Who is signed in (demo), as chosen — known at once, before their details load. */
  customerId?: number;
  /** The signed-in (demo) customer, with addresses; undefined for a guest or while loading. */
  customer?: CustomerDetail;
  /** A customer is chosen but their details haven't arrived yet. */
  customerLoading: boolean;
  setCustomerId: (id: number | undefined) => void;
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
  /** Customers, stores or categories failed to load (e.g. the API isn't running). */
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
  const [customerId, setCustomerId] = useStoredId("jb.shop.customerId");
  const [storeId, setStoreId] = useStoredId("jb.shop.storeId");

  const customers = useLoad("customers", () => call(api.GET("/api/v1/customers")));
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
  // A stale choice (e.g. the database was rebuilt and the customer is gone) ends as a guest, not a spinner.
  const customerLoading = customerId !== undefined && !customer && !detail.error;
  // Don't guess a store from the first one while the customer's state is still on its way.
  const store = retailStores.find((s) => s.store_id === storeId)
    ?? (customerLoading ? undefined : retailStores.find((s) => s.state === homeState) ?? retailStores[0]);

  const shop: Shop = {
    customers: customers.data ?? [],
    customerId,
    customer,
    customerLoading,
    setCustomerId,
    retailStores,
    store,
    setStoreId,
    homeState,
    categories: categories.data ?? [],
    loadError: customers.error ?? stores.error ?? categories.error,
    reload: () => {
      customers.reload();
      stores.reload();
      categories.reload();
    },
  };
  return <ShopContext value={shop}>{children}</ShopContext>;
}

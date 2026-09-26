"use client";

import { createContext, type ReactNode, useContext } from "react";

import { type ApiError, api, call, type Category, type Customer, type CustomerDetail, type Store } from "@/lib/api/client";
import { useStoredId } from "@/lib/browser-storage";
import { ensureSession, type Session } from "@/lib/session";
import { useLoad } from "@/lib/use-load";

// ---------------------------------------------------------------- shop context

type Shop = {
  customers: Customer[];
  /** The picker's choice in this browser, known at once — the session may still be confirming it. */
  chosenCustomerId?: number;
  /** Who is signed in (demo): the customer the session cookie says we are, not just the picker's choice. */
  customerId?: number;
  /** The signed-in (demo) customer, with addresses; undefined for a guest or while loading. */
  customer?: CustomerDetail;
  /** A customer is chosen but their details haven't arrived yet. */
  customerLoading: boolean;
  setCustomerId: (id: number | undefined) => void;
  /** The verified demo session (the storefront is always the chosen customer, or a guest). */
  session?: Session;
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
  /** The signed-in customer's details failed to load. */
  customerError?: ApiError;
  /** Try the failed loads again, including the customer's own record. */
  reload: () => void;
};

const ShopContext = createContext<Shop | null>(null);

export function useShop(): Shop {
  const shop = useContext(ShopContext);
  if (!shop) throw new Error("useShop() must be used inside <ShopProvider>");
  return shop;
}

export function ShopProvider({ children }: { children: ReactNode }) {
  // The picker's choice is a browser convenience; the API trusts only the signed cookie it issues.
  const [chosenCustomerId, setCustomerId] = useStoredId("jb.shop.customerId");
  const [storeId, setStoreId] = useStoredId("jb.shop.storeId");

  const customers = useLoad("customers", () => call(api.GET("/api/v1/customers")));
  const stores = useLoad("stores", () => call(api.GET("/api/v1/stores")));
  const categories = useLoad("categories", () => call(api.GET("/api/v1/categories")));
  // Declare who this surface acts as (the storefront is always a customer), then read that customer's
  // own record — which the API only serves to the session that owns it.
  const session = useLoad(`shop-session:${chosenCustomerId ?? "guest"}`,
    () => ensureSession("customer", chosenCustomerId));
  const sessionCustomerId = session.data?.kind === "customer" ? session.data.id : undefined;
  const detail = useLoad(`customer:${sessionCustomerId ?? "guest"}`, () =>
    sessionCustomerId === undefined
      ? Promise.resolve(undefined)
      : call(api.GET("/api/v1/customers/{customer_id}", { params: { path: { customer_id: sessionCustomerId } } })));

  // While another customer loads, don't show the previous one's details under the new name.
  const customer = detail.data?.customer_id === sessionCustomerId ? detail.data : undefined;
  const homeState = customer?.addresses.find((a) => a.is_active)?.state;
  const retailStores = (stores.data ?? []).filter((s) => s.store_type === "retail");
  const customerError = detail.error ?? session.error;
  // A stale choice (e.g. the database was rebuilt and the customer is gone) ends as a guest, not a spinner.
  const customerLoading = sessionCustomerId !== undefined && !customer && !customerError;
  // Don't guess a store from the first one while the customer's state is still on its way.
  const store = retailStores.find((s) => s.store_id === storeId)
    ?? (customerLoading ? undefined : retailStores.find((s) => s.state === homeState) ?? retailStores[0]);

  const shop: Shop = {
    customers: customers.data ?? [],
    chosenCustomerId,
    customerId: sessionCustomerId,
    customer,
    customerLoading,
    setCustomerId,
    session: session.data ?? undefined,
    retailStores,
    store,
    setStoreId,
    homeState,
    categories: categories.data ?? [],
    loadError: customers.error ?? stores.error ?? categories.error,
    customerError,
    reload: () => {
      customers.reload();
      stores.reload();
      categories.reload();
      session.reload();
      detail.reload();
    },
  };
  return <ShopContext value={shop}>{children}</ShopContext>;
}

"use client";

import { createContext, type ReactNode, useContext } from "react";

import { type ApiError, api, call, type Category, type CustomerDetail, type Store } from "@/lib/api/client";
import { useStoredId } from "@/lib/browser-storage";
import { type MeState, useMe } from "@/lib/me";
import { useLoad } from "@/lib/use-load";

// Which store is "mine" is a convenience for this browser only, so it lives in localStorage
// (lib/browser-storage.ts). Who is signed in is Clerk's business: see useMe.

// ---------------------------------------------------------------- shop context

type Shop = {
  /** Who is signed in, as the API sees them (a Clerk sign-in, mapped to our data by GET /me). */
  session: MeState;
  /** The signed-in customer, with addresses; undefined for a guest, for staff, or while loading. */
  customer?: CustomerDetail;
  /** Still finding out who is signed in, or their details haven't arrived yet. */
  customerLoading: boolean;
  /** The signed-in customer's own record failed to load: pages show the error instead of "sign in". */
  customerError?: ApiError;
  /** Read the signed-in customer's record again, e.g. after adding or retiring an address. */
  reloadCustomer: () => void;
  /** Every store, the warehouse included: a delivery can ship from any store with stock. */
  stores: Store[];
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
  /** Try those loads again, and the customer's record. */
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
  const allStores = stores.data ?? [];
  const retailStores = allStores.filter((s) => s.store_type === "retail");
  const customerLoading = session.status === "loading" || (customerId !== undefined && !customer && !detail.error);
  // Don't guess a store from the first one while the customer's state is still on its way.
  const store = retailStores.find((s) => s.store_id === storeId)
    ?? (customerLoading ? undefined : retailStores.find((s) => s.state === homeState) ?? retailStores[0]);

  const shop: Shop = {
    session,
    customer,
    customerLoading,
    customerError: detail.error,
    reloadCustomer: detail.reload,
    stores: allStores,
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
      detail.reload();
    },
  };
  return <ShopContext value={shop}>{children}</ShopContext>;
}

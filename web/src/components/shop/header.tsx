"use client";

import Form from "next/form";
import Link from "next/link";

import { useShop } from "@/components/shop/context";
import { SHOP_PAGES } from "@/lib/shop-pages";

const pickerClass =
  "h-9 max-w-[12rem] rounded-md border border-neutral-900/15 bg-white/80 px-2 text-sm text-neutral-900 " +
  "focus:outline-none focus:ring-2 focus:ring-neutral-900";

export function ShopHeader() {
  const { customers, chosenCustomerId, setCustomerId, retailStores, store, setStoreId, categories } = useShop();
  const states = [...new Set(retailStores.map((s) => s.state))];

  return (
    <header>
      <div className="bg-yellow-300">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-3 px-4 py-3">
          <Link href="/" className="flex items-center gap-2" aria-label="JB Hi-Fi home">
            <span className="rounded bg-neutral-900 px-2 py-1 text-lg font-black italic tracking-tight text-yellow-300">
              JB HI-FI
            </span>
          </Link>

          {/* A plain GET form: the catalogue page receives ?q= (next/form navigates client-side). */}
          <Form action={SHOP_PAGES.catalogue.href} role="search" className="flex min-w-[12rem] flex-1">
            <input name="q" type="search" placeholder="Search products, brands, SKUs" aria-label="Search products"
              className="h-10 w-full rounded-l-md border border-neutral-900/20 bg-white px-3 text-sm
                focus:outline-none focus:ring-2 focus:ring-neutral-900" />
            <button type="submit"
              className="h-10 rounded-r-md bg-neutral-900 px-4 text-sm font-semibold text-white hover:bg-neutral-700">
              Search
            </button>
          </Form>

          <label className="flex items-center gap-2 text-xs font-medium text-neutral-800">
            My store
            <select className={pickerClass} value={store?.store_id ?? ""}
              onChange={(e) => setStoreId(Number(e.target.value))}>
              {states.map((state) => (
                <optgroup key={state} label={state}>
                  {retailStores.filter((s) => s.state === state).map((s) => (
                    <option key={s.store_id} value={s.store_id}>{s.name}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-2 text-xs font-medium text-neutral-800"
            title="Demo sign-in: pick a customer. A real login replaces this later.">
            Signed in as
            <select className={pickerClass}
              value={customers.some((c) => c.customer_id === chosenCustomerId) ? chosenCustomerId : ""}
              onChange={(e) => {
                setCustomerId(e.target.value ? Number(e.target.value) : undefined);
                setStoreId(undefined);        // back to the new customer's nearest store
              }}>
              <option value="">Guest</option>
              {customers.map((c) => <option key={c.customer_id} value={c.customer_id}>{c.full_name}</option>)}
            </select>
          </label>

          <Link href={SHOP_PAGES.cart.href}
            className="flex h-10 items-center gap-2 rounded-md px-3 text-sm font-semibold text-neutral-900 hover:bg-yellow-400">
            <CartIcon /> Cart
          </Link>
        </div>
      </div>

      <nav aria-label="Shop" className="bg-neutral-900 text-sm text-neutral-200">
        <div className="mx-auto flex max-w-7xl flex-col lg:flex-row lg:items-center">
          {/* Account links come first on narrow screens, so they are never scrolled out of view; from lg they sit
              on the right and only the categories scroll. */}
          <div className="flex shrink-0 overflow-x-auto border-b border-neutral-800 px-2 lg:order-last lg:border-0">
            {[
              { href: "/#deals", label: "Deals" },
              { href: SHOP_PAGES.stores.href, label: "Stores" },
              { href: SHOP_PAGES.orders.href, label: "My orders" },
              { href: SHOP_PAGES.returns.href, label: "Returns" },
              { href: SHOP_PAGES.account.href, label: "Account" },
            ].map((link) => (
              <Link key={link.href} href={link.href}
                className="whitespace-nowrap px-2.5 py-2.5 hover:bg-neutral-800 hover:text-white lg:px-3">
                {link.label}
              </Link>
            ))}
          </div>
          <div className="flex min-w-0 flex-1 overflow-x-auto px-2">
            {categories.filter((c) => c.parent_id === null).map((c) => (
              <Link key={c.category_id} href={`${SHOP_PAGES.catalogue.href}?category=${c.category_id}`}
                className="whitespace-nowrap px-2.5 py-2.5 hover:bg-neutral-800 hover:text-white lg:px-3">
                {c.name}
              </Link>
            ))}
          </div>
        </div>
      </nav>
    </header>
  );
}

function CartIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round">
      <circle cx="9" cy="20" r="1.5" />
      <circle cx="18" cy="20" r="1.5" />
      <path d="M2 3h3l2.7 12.2a2 2 0 0 0 2 1.6h8.1a2 2 0 0 0 2-1.5L22 7H6" />
    </svg>
  );
}

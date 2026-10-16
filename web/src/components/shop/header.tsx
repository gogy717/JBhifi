"use client";

import { Show, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";
import Form from "next/form";
import Link from "next/link";
import type { ReactNode } from "react";

import { LogoMark, Wordmark } from "@/components/brand";
import { useShop } from "@/components/shop/context";
import { useCart } from "@/lib/cart-context";
import type { MeState } from "@/lib/me";
import { SHOP_PAGES } from "@/lib/shop-pages";

const container = "mx-auto max-w-[1280px] px-6";

/** The storefront's header: a dark utility bar (where Click & Collect is from, and the customer's pages), the logo
 *  with search, "My store", sign-in and the cart, and a bar of the top-level categories. */
export function ShopHeader() {
  const { session, retailStores, store, setStoreId, categories } = useShop();
  const { count } = useCart();
  const states = [...new Set(retailStores.map((s) => s.state))];

  return (
    <header>
      <div className="bg-ink text-[13px] text-on-ink">
        <div className={`${container} flex flex-wrap items-center justify-between gap-x-6 gap-y-2 py-2.5`}>
          <div className="flex items-center gap-2">
            <Icon className="h-3.5 w-3.5 text-ember" strokeWidth={2.2}>
              <path d="M20 7l-8-4-8 4v10l8 4 8-4z" /><path d="M4 7l8 4 8-4" /><path d="M12 11v10" />
            </Icon>
            <span>Click &amp; Collect from {store
              ? <strong className="font-semibold text-white">{store.name}</strong>
              : "your local store"}</span>
          </div>
          <nav aria-label="Your account" className="flex gap-5">
            {[
              { href: SHOP_PAGES.stores.href, label: "Stores" },
              { href: SHOP_PAGES.orders.href, label: "My orders" },
              { href: SHOP_PAGES.returns.href, label: "Returns" },
            ].map((link) => (
              <Link key={link.href} href={link.href} className="hover:text-white">{link.label}</Link>
            ))}
          </nav>
        </div>
      </div>

      <div className="border-b border-line bg-white">
        <div className={`${container} flex flex-wrap items-center gap-x-6 gap-y-4 py-[18px]`}>
          <Link href="/" className="flex shrink-0 items-center gap-2.5 text-ink" aria-label="TechLight home">
            <LogoMark className="h-10 w-10" />
            <Wordmark className="text-[26px]" />
          </Link>

          {/* A plain GET form: the catalogue page receives ?q= (next/form navigates client-side). */}
          <Form action={SHOP_PAGES.catalogue.href} role="search"
            className="flex min-w-0 flex-[1_1_340px] items-center gap-2.5 rounded-full bg-sand py-1 pl-[18px] pr-1
              focus-within:ring-2 focus-within:ring-brand">
            <Icon className="h-[18px] w-[18px] text-muted" strokeWidth={2.2}>
              <circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" />
            </Icon>
            <input name="q" type="search" placeholder="Search products, brands, SKUs" aria-label="Search products"
              className="min-w-0 flex-1 bg-transparent py-2.5 text-base text-ink placeholder:text-faint
                focus:outline-none" />
            <button type="submit"
              className="h-11 shrink-0 rounded-full bg-brand-strong px-[22px] text-[15px] font-bold text-white
                hover:brightness-90">
              Search
            </button>
          </Form>

          <div className="flex flex-wrap items-center gap-2">
            <label className="relative flex h-11 items-center gap-2 rounded-full border border-line bg-white pl-3.5
              pr-9 text-[15px] focus-within:ring-2 focus-within:ring-brand">
              <Icon className="h-[18px] w-[18px] text-brand-strong" strokeWidth={2.2}>
                <path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z" /><circle cx="12" cy="9.5" r="2.5" />
              </Icon>
              <span className="whitespace-nowrap text-muted">My store</span>
              {/* The native control, so the keyboard and screen readers work as everywhere else; only its look is
                  the design's (a pill with a chevron). */}
              <select value={store?.store_id ?? ""} onChange={(e) => setStoreId(Number(e.target.value))}
                className="max-w-[10rem] cursor-pointer appearance-none truncate bg-transparent font-bold text-ink
                  focus:outline-none">
                {states.map((state) => (
                  <optgroup key={state} label={state}>
                    {retailStores.filter((s) => s.state === state).map((s) => (
                      <option key={s.store_id} value={s.store_id}>{s.name}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
              <Icon className="pointer-events-none absolute right-3.5 h-3.5 w-3.5 text-muted" strokeWidth={2.4}>
                <path d="M6 9l6 6 6-6" />
              </Icon>
            </label>

            <AccountControls session={session} />

            <Link href={SHOP_PAGES.cart.href}
              aria-label={count > 0 ? `Cart, ${count} ${count === 1 ? "item" : "items"}` : "Cart"}
              className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-sand text-ink
                hover:bg-line">
              <Icon className="h-[22px] w-[22px]">
                <path d="M3 4h2l2.4 11.2a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.5L21 8H6" />
                <circle cx="10" cy="20.5" r="1.3" /><circle cx="17" cy="20.5" r="1.3" />
              </Icon>
              {count > 0 && (
                <span aria-hidden="true" className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center
                  justify-center rounded-full bg-brand-strong px-1 text-[11px] font-bold text-white ring-2 ring-white">
                  {count}
                </span>
              )}
            </Link>
          </div>
        </div>

        <nav aria-label="Categories" className="border-t border-line">
          <div className={`${container} flex items-center gap-1 overflow-x-auto whitespace-nowrap text-[15px]
            font-semibold`}>
            <Link href="/#deals" className="flex items-center gap-1.5 px-3 py-3.5 text-brand-strong hover:underline">
              <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4 fill-current">
                <path d="M13 2L4 14h7l-1 8 9-12h-7z" />
              </svg>
              Deals
            </Link>
            {categories.filter((c) => c.parent_id === null).map((c) => (
              <Link key={c.category_id} href={`${SHOP_PAGES.catalogue.href}?category=${c.category_id}`}
                className="px-3 py-3.5 hover:text-brand-strong">
                {c.name}
              </Link>
            ))}
            <div className="flex-1" />
            <Link href={SHOP_PAGES.account.href} className="px-3 py-3.5 font-medium text-muted hover:text-ink">
              Account
            </Link>
          </div>
        </nav>
      </div>
    </header>
  );
}

function AccountControls({ session }: { session: MeState }) {
  return (
    <div className="flex items-center gap-2 text-[15px]">
      <Show when="signed-out">
        <SignInButton mode="modal">
          <button type="button" className="flex h-11 items-center gap-2 rounded-full px-3 font-semibold text-ink
            hover:bg-sand">
            <Icon className="h-5 w-5"><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></Icon>
            Sign in
          </button>
        </SignInButton>
        <SignUpButton mode="modal">
          <button type="button" className="h-11 rounded-full bg-ink px-[18px] font-bold text-white hover:bg-neutral-700">
            Create account
          </button>
        </SignUpButton>
      </Show>
      <Show when="signed-in">
        {session.status === "signed-in" && (
          <span className="whitespace-nowrap font-semibold text-ink">
            {session.me.display_name}
            {session.me.kind === "staff" && <span className="font-normal text-muted"> · staff</span>}
          </span>
        )}
        <UserButton />
      </Show>
    </div>
  );
}

/** A line icon from the design, drawn in currentColor. Decorative: the text next to it says what it is. */
function Icon({ className, strokeWidth = 2, children }: { className: string; strokeWidth?: number; children: ReactNode }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className={`shrink-0 ${className}`} fill="none" stroke="currentColor"
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  );
}

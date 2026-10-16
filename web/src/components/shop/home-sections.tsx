"use client";

import { SignInButton, SignUpButton } from "@clerk/nextjs";
import Link from "next/link";
import { type ReactNode, useId, useState } from "react";

import { CategoryIcon, ProductImage } from "@/components/product-image";
import { StoreLine } from "@/components/shop/product-card";
import { Badge, Button, Dot, ErrorBox } from "@/components/ui";
import type { ApiError, Category, CustomerDetail, Promotion, Store } from "@/lib/api/client";
import { saving } from "@/lib/deals";
import { formatDate, formatLastDay, money, percentOff } from "@/lib/format";
import type { MeState } from "@/lib/me";
import { SHOP_PAGES } from "@/lib/shop-pages";

// The home page's sections, from the homepage design. Everything they show is live data from the API; the page
// (app/(shop)/page.tsx) loads it and lays the sections out.

const pill = "inline-flex items-center justify-center rounded-full font-bold transition";

// A deal card's "Ends" pill: the last day of the half-open period, as day and month (formatLastDay adds the year).
const dayMonth = new Intl.DateTimeFormat("en-AU", { day: "numeric", month: "short" });
const lastDayShort = (endIso: string) => dayMonth.format(new Date(new Date(endIso).getTime() - 1));

export function SectionHeading({ title, note, live = false, action }: {
  title: string;
  note?: ReactNode;
  /** A green dot before the note: the section shows data as it is now. */
  live?: boolean;
  action?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="flex flex-col gap-2">
        <h2 className="text-[28px] font-bold leading-tight tracking-[-0.02em]">{title}</h2>
        {note && (
          <p className="flex items-center gap-2 text-[15px] text-muted">{live && <Dot className="bg-ok" />}{note}</p>
        )}
      </div>
      {action}
    </div>
  );
}

// ---------------------------------------------------------------- hero

/** The red hero: what the store is about, with the deal of the week beside it. */
export function Hero({ storeName, children }: { storeName?: string; children: ReactNode }) {
  const titleId = useId();
  return (
    <section aria-labelledby={titleId}
      className="flex flex-wrap items-center gap-10 overflow-hidden rounded-hero bg-brand p-7 sm:p-14">
      <div className="flex min-w-0 flex-[1_1_420px] flex-col gap-5 text-white">
        <span className="self-start rounded-full bg-ink px-3.5 py-2 text-[13px] font-bold uppercase tracking-[0.06em]">
          Live deals · {storeName ?? "your store"}
        </span>
        <h1 id={titleId}
          className="text-[44px] font-extrabold leading-[1.02] tracking-[-0.035em] sm:text-[64px]">
          Big tech.<br />Bright prices.
        </h1>
        {/* Bold, not the design's semibold: white on #E64626 is 4.0:1, which AA allows only for large (bold 19px+)
            text. */}
        <p className="max-w-[460px] text-xl font-bold leading-[1.45]">
          Promotions running now, with live stock at your store. Order online and Click &amp; Collect today.
        </p>
        <div className="mt-2 flex flex-wrap gap-3">
          <Link href="#deals" className={`${pill} h-[52px] bg-white px-[26px] text-base text-ink hover:bg-sand`}>
            Shop all deals
          </Link>
          <Link href={SHOP_PAGES.stores.href}
            className={`${pill} h-[52px] bg-ink px-[26px] text-base text-white hover:bg-neutral-800`}>
            Find a store
          </Link>
        </div>
      </div>
      {children}
    </section>
  );
}

/** The live promotion with the biggest discount, with its stock at my store. */
export function DealOfTheWeek({ deal, categoryId, categories, store, quantity, loading = false }: {
  deal?: Promotion;
  categoryId?: number;
  categories: Category[];
  store?: Store;
  quantity?: number;
  loading?: boolean;
}) {
  const box = "flex min-w-0 max-w-[520px] flex-[1_1_360px] flex-col gap-4 rounded-[22px] bg-white p-5 text-ink";
  if (loading) return <div aria-hidden="true" className={`${box} h-[380px] animate-pulse`} />;
  if (!deal) {
    return (
      <div className={box}>
        <ProductImage categories={categories} className="h-60 rounded-[14px]" iconClassName="h-16 w-16" />
        <p className="text-lg font-semibold">No deals running right now.</p>
        <Link href={SHOP_PAGES.catalogue.href}
          className={`${pill} h-11 self-start bg-ink px-5 text-[15px] text-white hover:bg-neutral-700`}>
          Shop all products
        </Link>
      </div>
    );
  }
  return (
    <Link href={`${SHOP_PAGES.catalogue.href}/${deal.product_id}`} className={`${box} group transition hover:shadow-xl`}>
      <ProductImage categoryId={categoryId} categories={categories} brand={deal.brand} className="h-60 rounded-[14px]"
        iconClassName="h-16 w-16">
        <span className="absolute left-3.5 top-3.5 rounded-full bg-brand-strong px-3 py-1.5 text-[15px] font-extrabold
          uppercase text-white">
          {percentOff(deal.base_price, deal.sale_price)}
        </span>
      </ProductImage>
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-[1_1_220px] flex-col gap-1">
          <span className="text-xs font-bold uppercase tracking-[0.08em] text-muted">{deal.brand} · Deal of the week</span>
          <span className="text-lg font-semibold group-hover:text-brand-strong">{deal.product_name}</span>
        </div>
        {/* Beside the name it lines up on the right; on a phone it wraps under the name and starts on the left. */}
        <div className="flex shrink-0 flex-col items-start sm:items-end">
          <span className="font-display text-[30px] font-extrabold tracking-[-0.02em]">{money(deal.sale_price)}</span>
          <s className="text-sm text-muted"><span className="sr-only">was </span>{money(deal.base_price)}</s>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <StoreLine quantity={quantity} storeName={store?.name} className="" />
        <span className="text-[13px] text-muted">Ends {formatLastDay(deal.ends_at)}</span>
      </div>
    </Link>
  );
}

// ---------------------------------------------------------------- categories

/** A card per top-level category, with its icon and its subcategories: the tree is a recursive relationship. */
export function CategoryGrid({ categories }: { categories: Category[] }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fit,minmax(190px,1fr))] sm:gap-4">
      {categories.filter((c) => c.parent_id === null).map((top) => {
        const subcategories = categories.filter((c) => c.parent_id === top.category_id).map((c) => c.name);
        return (
          <Link key={top.category_id} href={`${SHOP_PAGES.catalogue.href}?category=${top.category_id}`}
            className="group flex flex-col gap-5 rounded-card border border-line bg-white p-4 transition sm:gap-7 sm:p-[22px]
              hover:border-brand-strong/40 hover:shadow-sm">
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-soft text-brand-strong">
              <CategoryIcon categoryId={top.category_id} categories={categories} />
            </span>
            <span className="flex flex-col gap-1">
              <span className="flex items-center justify-between gap-2 text-[17px] font-bold group-hover:text-brand-strong">
                {top.name} <span aria-hidden="true">→</span>
              </span>
              {subcategories.length > 0 && <span className="text-[13px] text-muted">{subcategories.join(" · ")}</span>}
            </span>
          </Link>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- deals

/** One running promotion: the discount and its last day, the prices, what it saves, the stock at my store. */
export function DealCard({ deal, categoryId, categories, store, quantity, onAdd }: {
  deal: Promotion;
  categoryId?: number;
  categories: Category[];
  store?: Store;
  quantity?: number;
  onAdd: (deal: Promotion) => void;
}) {
  return (
    <article className="flex flex-col gap-3.5 rounded-card border border-line bg-white p-3.5">
      <ProductImage categoryId={categoryId} categories={categories} brand={deal.brand} className="h-[180px] rounded-tile">
        <span className="absolute left-2.5 top-2.5"><Badge tone="sale">
          <span className="uppercase">{percentOff(deal.base_price, deal.sale_price)}</span>
        </Badge></span>
        <span className="absolute right-2.5 top-2.5 rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-muted">
          Ends {lastDayShort(deal.ends_at)}
        </span>
      </ProductImage>
      <div className="flex flex-1 flex-col gap-1 px-1">
        <span className="text-xs font-bold uppercase tracking-[0.08em] text-muted">{deal.brand}</span>
        <Link href={`${SHOP_PAGES.catalogue.href}/${deal.product_id}`}
          className="text-base font-semibold leading-snug hover:text-brand-strong">
          {deal.product_name}
        </Link>
      </div>
      <div className="flex flex-col gap-1.5 px-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-display text-2xl font-extrabold tracking-[-0.02em]">{money(deal.sale_price)}</span>
          <s className="text-sm text-muted"><span className="sr-only">was </span>{money(deal.base_price)}</s>
        </div>
        <span className="text-sm font-bold text-brand-strong">Save {money(saving(deal))}</span>
        <StoreLine quantity={quantity} storeName={store?.name} className="" />
      </div>
      <Button tone="primary" onClick={() => onAdd(deal)}>Add to cart</Button>
    </article>
  );
}

/** Promotions that haven't started yet. */
export function StartingSoon({ deals }: { deals: Promotion[] }) {
  if (deals.length === 0) return null;
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-card bg-ink px-5 py-3.5 text-sm text-on-ink">
      <span className="text-[13px] font-bold uppercase tracking-[0.08em] text-ember">Starting soon</span>
      {deals.map((p) => (
        <span key={p.promotion_id}>
          {p.brand} {p.product_name} <b className="text-white">{money(p.sale_price)}</b>
          <span className="text-on-ink-muted"> from {formatDate(p.starts_at)}</span>
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- my store and my account

/** "Your store": the store whose Click & Collect and stock the site shows. "Change store" lists the other stores
 *  nearby to choose from; every store is on the Stores page. */
export function StorePanel({ store, nearby, nearState, onChoose }: {
  store?: Store;
  nearby: Store[];
  nearState?: string;
  onChoose: (storeId: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const others = nearby.filter((s) => s.store_id !== store?.store_id);
  return (
    <section aria-label="Your store"
      className="flex min-w-0 flex-[2_1_420px] flex-col gap-6 rounded-panel bg-ink p-7 text-white sm:p-9">
      <div className="flex flex-wrap items-center justify-between gap-6">
        <div className="flex flex-col gap-2">
          <span className="text-[13px] font-bold uppercase tracking-[0.08em] text-ember">Your store</span>
          <span className="font-display text-[30px] font-bold leading-tight tracking-[-0.02em]">
            {store?.name ?? "…"} {store && <span className="font-semibold text-on-ink-muted">{store.state}</span>}
          </span>
          <span className="text-base text-on-ink">
            Click &amp; Collect and stock levels on this site are shown for this store.
          </span>
          {store && <span className="text-sm text-on-ink-muted">Manager: {store.manager_name}</span>}
        </div>
        <div className="flex flex-wrap gap-2.5">
          <button type="button" aria-expanded={open} aria-controls={listId} onClick={() => setOpen(!open)}
            className={`${pill} h-12 bg-brand-strong px-[22px] text-white hover:brightness-110`}>
            Change store
          </button>
          <Link href={SHOP_PAGES.stores.href}
            className={`${pill} h-12 border border-muted px-[22px] text-white hover:bg-white/10`}>
            Find a store
          </Link>
        </div>
      </div>
      {open && (
        <ul id={listId} aria-label={nearState ? `Stores in ${nearState}` : "Stores nearby"}
          className="flex flex-wrap gap-2 border-t border-white/10 pt-5">
          {others.length === 0 && (
            <li className="text-sm text-on-ink-muted">No other stores nearby: the Stores page has them all.</li>
          )}
          {others.map((s) => (
            <li key={s.store_id}>
              <button type="button" onClick={() => { onChoose(s.store_id); setOpen(false); }}
                className="rounded-full bg-white/10 px-4 py-2 text-sm font-semibold text-white hover:bg-white/20">
                {s.name} <span className="font-normal text-on-ink-muted">{s.suburb}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** "Make it yours" for a guest; a greeting and the delivery address for a customer; a note for staff. */
export function AccountPanel({ session, customer, loading, error }: {
  session: MeState;
  customer?: CustomerDetail;
  loading: boolean;
  error?: ApiError;
}) {
  const box = "flex min-w-0 flex-[1_1_300px] flex-col justify-center gap-4 rounded-panel bg-brand-soft p-7 sm:p-9";
  const title = "font-display text-[22px] font-bold tracking-[-0.02em]";
  const inkPill = `${pill} h-11 bg-ink px-5 text-[15px] text-white hover:bg-neutral-700`;
  const whitePill = `${pill} h-11 bg-white px-5 text-[15px] text-ink hover:bg-sand`;

  if (loading) {
    return (
      <div aria-hidden="true" className={box}>
        <div className="h-7 w-40 animate-pulse rounded-full bg-white/70" />
        <div className="h-5 w-full animate-pulse rounded-full bg-white/70" />
      </div>
    );
  }
  if (session.status === "signed-in" && session.me.kind === "staff") {
    return (
      <div className={box}>
        <h2 className={title}>Signed in as staff</h2>
        <p className="text-base text-muted">
          The storefront shows you what a guest sees: staff accounts have no orders or returns here.
        </p>
        <Link href="/admin" className={`${inkPill} self-start`}>Go to the store admin</Link>
      </div>
    );
  }
  if (session.status === "signed-in") {
    const address = customer?.addresses.find((a) => a.is_active);
    return (
      <div className={box}>
        <h2 className={title}>{customer ? `Hi, ${customer.full_name.split(" ")[0]}` : `Hi, ${session.me.display_name}`}</h2>
        {error ? <ErrorBox error={error} />
          : (
            <p className="text-base text-muted">
              {address ? <>Delivering to {address.line1}, {address.suburb} {address.state} {address.postcode}.</>
                : "No current delivery address — add one in My account."}
            </p>
          )}
        <div className="flex flex-wrap gap-2.5">
          <Link href={SHOP_PAGES.orders.href} className={inkPill}>My orders</Link>
          <Link href={SHOP_PAGES.account.href} className={whitePill}>My account</Link>
        </div>
      </div>
    );
  }
  return (
    <div className={box}>
      <h2 className={title}>Make it yours</h2>
      <p className="text-base text-muted">
        {session.status === "error" ? session.error.message
          : "Sign in to see a personal home page, your orders and returns."}
      </p>
      {session.status !== "error" && (
        <div className="flex flex-wrap gap-2.5">
          <SignInButton mode="modal"><button type="button" className={inkPill}>Sign in</button></SignInButton>
          <SignUpButton mode="modal"><button type="button" className={whitePill}>Create account</button></SignUpButton>
        </div>
      )}
    </div>
  );
}

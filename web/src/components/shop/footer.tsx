"use client";

import Link from "next/link";

import { LogoMark, Wordmark } from "@/components/brand";
import { useShop } from "@/components/shop/context";
import { SHOP_PAGES } from "@/lib/shop-pages";

/** The storefront's footer: the logo, the top-level categories, the customer's pages, the line that says the store
 *  is fictional, and the way into the store admin. */
export function ShopFooter() {
  const { categories } = useShop();
  const shop = categories.filter((c) => c.parent_id === null)
    .map((c) => ({ href: `${SHOP_PAGES.catalogue.href}?category=${c.category_id}`, label: c.name }));
  const help = [
    { href: SHOP_PAGES.stores.href, label: "Stores" },
    { href: SHOP_PAGES.orders.href, label: "My orders" },
    { href: SHOP_PAGES.returns.href, label: "Returns" },
    { href: SHOP_PAGES.account.href, label: "Account" },
  ];

  return (
    <footer className="bg-ink text-on-ink-muted">
      <div className="mx-auto flex max-w-[1280px] flex-col gap-10 px-6 pb-8 pt-14">
        <div className="flex flex-wrap gap-x-20 gap-y-10">
          <div className="flex flex-[1_1_260px] flex-col gap-3.5">
            <Link href="/" aria-label="TechLight home" className="flex items-center gap-2.5 self-start text-white">
              <LogoMark className="h-9 w-9" />
              <Wordmark className="text-[22px]" />
            </Link>
            <p className="max-w-[280px] text-[15px]">
              Tech, audio and entertainment, with Click &amp; Collect from your local store.
            </p>
          </div>
          <FooterLinks title="Shop" links={shop} />
          <FooterLinks title="Help" links={help} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-5 text-[13px]">
          <span>© 2026 TechLight — a fictional store, built as a COMP9120 prototype. Payments are simulated.</span>
          <Link href="/admin" className="font-semibold text-on-ink hover:text-white">Staff: store admin →</Link>
        </div>
      </div>
    </footer>
  );
}

function FooterLinks({ title, links }: { title: string; links: { href: string; label: string }[] }) {
  return (
    <nav aria-label={title} className="flex flex-col gap-2.5 text-[15px]">
      <span className="font-bold text-white">{title}</span>
      {links.map((link) => (
        <Link key={link.href} href={link.href} className="hover:text-white">{link.label}</Link>
      ))}
    </nav>
  );
}

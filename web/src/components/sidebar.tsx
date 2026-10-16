"use client";

import { UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { useSelectedLayoutSegment } from "next/navigation";
import type { ComponentType } from "react";

import {
  ArrowLeftIcon, InventoryIcon, OrdersIcon, ProductsIcon, PromotionsIcon, ReportsIcon, ReturnsIcon, StoreIcon,
  SupportIcon,
} from "@/components/admin/icons";
import { useStaff } from "@/components/admin/staff-gate";
import { LogoMark, Wordmark } from "@/components/brand";
import type { Me } from "@/lib/api/client";
import { useLoad } from "@/lib/use-load";

const LINKS: { href: string; label: string; hint: string; Icon: ComponentType<{ className?: string }> }[] = [
  { href: "/admin/orders", label: "Orders", hint: "Pick, hand over, cancel", Icon: OrdersIcon },
  { href: "/admin/inventory", label: "Inventory", hint: "Stock per store, ± adjustments", Icon: InventoryIcon },
  { href: "/admin/products", label: "Products", hint: "Catalogue, prices, specs", Icon: ProductsIcon },
  { href: "/admin/promotions", label: "Promotions", hint: "Sale prices over a period", Icon: PromotionsIcon },
  { href: "/admin/returns", label: "Returns", hint: "Receive, refund or reject", Icon: ReturnsIcon },
  { href: "/admin/reports", label: "Reports", hint: "Low stock, sales, return rate", Icon: ReportsIcon },
  { href: "/admin/support", label: "Support", hint: "Find a customer, see their history", Icon: SupportIcon },
];

/** The admin's navigation, on ink: the storefront is white, so the dark frame says "staff tool" at a glance and
 *  leaves the canvas and white cards beside it to the work. On a phone it sits on top and the links scroll
 *  sideways. */
export function Sidebar() {
  // The section below the layout that renders the sidebar: "orders" for /admin/orders and /admin/orders/42.
  const section = useSelectedLayoutSegment();
  return (
    <aside className="flex w-full shrink-0 flex-col bg-ink text-on-ink md:sticky md:top-0 md:h-screen md:w-64
      md:overflow-y-auto">
      <div className="flex items-center gap-3 px-5 pb-4 pt-5">
        <LogoMark className="h-10 w-10" />
        <div>
          <Wordmark className="text-[22px] text-white" />
          <div className="mt-1.5 text-[11px] font-bold uppercase tracking-[0.08em] text-ember">Store admin</div>
        </div>
      </div>
      <SignedInAs />
      <nav aria-label="Store admin" className="mt-3 flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:pb-0">
        {LINKS.map(({ href, label, hint, Icon }) => {
          const active = href === `/admin/${section}`;
          return (
            <Link key={href} href={href} aria-current={active ? "page" : undefined}
              className={`group relative flex shrink-0 items-center gap-3 rounded-full px-4 py-2 transition-colors
                focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-brand md:rounded-tile md:px-3
                md:py-2.5 ${active ? "bg-white/10 text-white" : "text-on-ink hover:bg-white/5 hover:text-white"}`}>
              {active && (
                <span aria-hidden="true" className="absolute inset-y-2 left-0 hidden w-1 rounded-full bg-brand md:block" />
              )}
              <Icon className={`h-5 w-5 ${active ? "text-brand" : "text-on-ink-muted group-hover:text-on-ink"}`} />
              <span className="min-w-0">
                <span className="block whitespace-nowrap text-[15px] font-semibold">{label}</span>
                <span className="hidden text-xs text-on-ink-muted md:block">{hint}</span>
              </span>
            </Link>
          );
        })}
      </nav>
      <Link href="/" className="mx-3 mb-3 flex items-center gap-2 rounded-full px-4 py-2 text-sm text-on-ink-muted
        transition-colors hover:bg-white/5 hover:text-white md:mx-3 md:mb-0 md:mt-4 md:px-3">
        <ArrowLeftIcon className="h-4 w-4" />
        Customer storefront
      </Link>
      <ApiStatus />
    </aside>
  );
}

/** "Staff · Sydney CBD", "Manager · Sydney CBD" or "Support · all stores". */
export function staffRole(me: Me): string {
  if (me.staff_type === "support") return "Support · all stores";
  return `${me.runs_store ? "Manager" : "Staff"} · ${me.store_name}`;
}

function SignedInAs() {
  const me = useStaff();
  return (
    <div className="mx-3 flex items-center gap-3 rounded-card bg-white/[0.06] px-3 py-3 ring-1 ring-white/10">
      <UserButton />
      <div className="min-w-0">
        <div className="truncate text-[15px] font-semibold text-white">{me.display_name}</div>
        <div className="flex items-center gap-1 truncate text-xs text-on-ink-muted">
          <StoreIcon className="h-3.5 w-3.5 text-ember" />
          {staffRole(me)}
        </div>
      </div>
    </div>
  );
}

function ApiStatus() {
  const health = useLoad("health", async () => {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error(response.statusText);
    return (await response.json()) as { status: string; db: string };
  });
  const ok = health.data !== undefined && !health.error;
  return (
    <div className="mt-auto hidden items-center gap-2 border-t border-white/10 px-5 py-4 text-xs text-on-ink-muted
      md:flex">
      <span className={`h-2 w-2 shrink-0 rounded-full ${ok ? "bg-emerald-400" : health.loading ? "bg-on-ink-muted"
        : "bg-red-500"}`} />
      <span className="min-w-0">
        {ok ? <>API connected · db <code className="text-on-ink">{health.data?.db}</code></>
          : health.loading ? "Checking API…" : "API unreachable"}
        {!ok && !health.loading && (
          <button type="button" onClick={health.reload} className="ml-1 underline hover:text-white">retry</button>
        )}
        <span className="block text-on-ink-muted/70">Phase 1 prototype</span>
      </span>
    </div>
  );
}

"use client";

import Link from "next/link";

import { StatusBadge } from "@/components/shop/order-timeline";
import { ErrorBox } from "@/components/ui";
import type { ApiError, OrderSummary } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";

/** The card style the home page's "My orders" and "Returns" share. */
export const recentCard = "rounded-card border border-line bg-white p-6";
export const recentRow = "-mx-3 flex items-center justify-between gap-3 rounded-xl px-3 py-3 hover:bg-sand";
export const recentPlaceholder = <div aria-hidden="true" className="mt-3 h-24 animate-pulse rounded-2xl bg-sand" />;

export function RecentHeading({ title, href, link }: { title: string; href: string; link: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <h2 className="text-xl font-bold tracking-[-0.02em]">{title}</h2>
      <Link href={href} className="text-sm font-bold text-brand-strong hover:underline">{link} →</Link>
    </div>
  );
}

/** The signed-in customer's newest orders (R5), each linking to its page. */
export function RecentOrders({ checking, signedIn, staff, orders, error }: {
  checking: boolean;
  signedIn: boolean;
  staff: boolean;
  orders?: OrderSummary[];
  error?: ApiError;
}) {
  const note = (text: string) => <p className="mt-2 text-[15px] text-muted">{text}</p>;
  return (
    <div className={recentCard}>
      <RecentHeading title="My orders" href={SHOP_PAGES.orders.href} link="All orders" />
      {checking ? recentPlaceholder
        : staff ? note("Staff accounts have no orders here.")
        : !signedIn ? note("Sign in to see your orders here.")
        : error ? <ErrorBox error={error} className="mt-3" />
        : !orders ? recentPlaceholder
        : orders.length === 0 ? note("No orders yet.")
        : (
          <ul className="mt-2 divide-y divide-line">
            {orders.map((order) => (
              <li key={order.order_id}>
                <Link href={`${SHOP_PAGES.orders.href}/${order.order_id}`} className={recentRow}>
                  <span>
                    <span className="font-semibold">Order #{order.order_id}</span>
                    <span className="block text-[13px] text-muted">{formatDateTime(order.placed_at)}</span>
                  </span>
                  <span className="flex items-center gap-3">
                    <span className="text-[15px] font-semibold tabular-nums">{money(order.total)}</span>
                    <StatusBadge status={order.status} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}

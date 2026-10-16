"use client";

import Link from "next/link";

import { ReturnStatusBadge } from "@/components/return-status";
import { useShop } from "@/components/shop/context";
import { recentCard, RecentHeading, recentPlaceholder, recentRow } from "@/components/shop/recent-orders";
import { ErrorBox } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

/** The home page's "Returns" card: the signed-in customer's 3 newest returns. */
export function RecentReturns() {
  const { session } = useShop();
  const customerId = session.status === "signed-in" && session.me.kind === "customer" ? session.me.id : undefined;
  const returns = useLoad(`returns:${customerId}`, () =>
    customerId === undefined
      ? Promise.resolve([])
      : call(api.GET("/api/v1/customers/{customer_id}/returns", { params: { path: { customer_id: customerId } } })));
  const newest = (returns.data ?? []).slice(0, 3);
  const note = (text: string) => <p className="mt-2 text-[15px] text-muted">{text}</p>;

  return (
    <div className={recentCard}>
      <RecentHeading title="Returns" href={SHOP_PAGES.returns.href} link="All returns" />
      {session.status === "loading" ? recentPlaceholder
        : session.status === "signed-in" && session.me.kind === "staff" ? note("Staff accounts have no returns here.")
        : customerId === undefined ? note("Sign in to see your returns here.")
        : returns.error ? <ErrorBox error={returns.error} className="mt-3" />
        : !returns.data ? recentPlaceholder
        : newest.length === 0 ? note("No returns. You can return items within 30 days of getting them.")
        : (
          <ul className="mt-2 divide-y divide-line">
            {newest.map((row) => (
              <li key={row.return_id}>
                <Link href={SHOP_PAGES.returns.href} className={recentRow}>
                  <span>
                    <span className="font-semibold">Return #{row.return_id}</span>
                    <span className="block text-[13px] text-muted">{formatDateTime(row.requested_at)}</span>
                  </span>
                  <span className="flex items-center gap-3">
                    <span className="text-[15px] font-semibold tabular-nums">{money(row.value)}</span>
                    <ReturnStatusBadge status={row.status} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}

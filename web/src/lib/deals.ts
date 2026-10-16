import type { Promotion } from "@/lib/api/client";

/** The share of the base price a promotion takes off, 0–1. */
export const discount = (p: Promotion) => 1 - Number(p.sale_price) / Number(p.base_price);

/** Running promotions worth advertising, biggest discount first: the first is the home page's deal of the week.
 *  A retired product's promotion is left out, because it can't be bought (BR07). */
export function liveDealsByDiscount(promotions: Promotion[] | undefined): Promotion[] {
  return (promotions ?? []).filter((p) => p.product_active).sort((a, b) => discount(b) - discount(a));
}

/** What a promotion saves, as a decimal string like the API's prices; worked out in whole cents, so a float's
 *  rounding never shows. */
export function saving(p: { base_price: string; sale_price: string }): string {
  const cents = Math.round(Number(p.base_price) * 100) - Math.round(Number(p.sale_price) * 100);
  return (cents / 100).toFixed(2);
}

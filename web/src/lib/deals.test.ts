import { describe, expect, it } from "vitest";

import type { Promotion } from "@/lib/api/client";

import { liveDealsByDiscount, saving } from "./deals";

const promo = (id: number, base: string, sale: string, active = true): Promotion => ({
  promotion_id: id, product_id: 100 + id, sku: `SKU-${id}`, brand: "Sony", product_name: `Product ${id}`,
  base_price: base, sale_price: sale, product_active: active,
  starts_at: "2026-10-01T00:00:00+11:00", ends_at: "2026-11-15T00:00:00+11:00", status: "active",
});

describe("liveDealsByDiscount", () => {
  it("puts_the_biggest_discount_first_so_it_can_be_the_deal_of_the_week", () => {
    const deals = liveDealsByDiscount([promo(1, "219.00", "189.00"), promo(2, "549.95", "399.00"),
      promo(3, "199.95", "149.95")]);
    expect(deals.map((d) => d.promotion_id)).toEqual([2, 3, 1]);
  });

  it("leaves_out_a_retired_products_promotion_because_it_cant_be_bought", () => {
    expect(liveDealsByDiscount([promo(1, "100.00", "10.00", false), promo(2, "100.00", "90.00")])
      .map((d) => d.promotion_id)).toEqual([2]);
  });

  it("no_promotions_is_no_deals", () => {
    expect(liveDealsByDiscount(undefined)).toEqual([]);
  });
});

describe("saving", () => {
  it("is_the_difference_in_whole_cents", () => {
    expect(saving(promo(1, "549.95", "399.00"))).toBe("150.95");
    expect(saving(promo(2, "0.30", "0.10"))).toBe("0.20");
  });
});

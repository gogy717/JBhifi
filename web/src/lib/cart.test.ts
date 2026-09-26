import { describe, expect, it } from "vitest";

import { addItem, fromCents, lineTotalCents, MAX_QUANTITY, readCart, removeItem, setQuantity, toCents,
  writeCart } from "./cart";

describe("money in cents", () => {
  it("multiplies and adds without floating-point drift", () => {
    expect(toCents("19.95") * 3).toBe(5985);
    expect(toCents("0.10") + toCents("0.20")).toBe(30);
    expect(toCents("189")).toBe(18900);
    expect(toCents("0.05")).toBe(5);
    expect(fromCents(5985)).toBe("59.85");
    expect(lineTotalCents("19.95", 3)).toBe(5985);
    expect(lineTotalCents("0.00", 9)).toBe(0);
  });
});

describe("the stored cart", () => {
  it("merges a product that is added twice", () => {
    const once = addItem([], 7, 2);
    const twice = addItem(once, 7, 1);
    expect(twice).toEqual([{ product_id: 7, quantity: 3 }]);
  });

  it("refuses quantities that are not positive whole numbers within range", () => {
    expect(addItem([], 1, 0)).toEqual([{ product_id: 1, quantity: 1 }]);       // clamped up to 1
    expect(addItem([], 1, -5)).toEqual([{ product_id: 1, quantity: 1 }]);
    expect(addItem([], 1, 1000)).toEqual([{ product_id: 1, quantity: MAX_QUANTITY }]);
    expect(addItem([], 1, 2.7)).toEqual([{ product_id: 1, quantity: 2 }]);
    // Setting zero or below removes the line rather than leaving an invalid one.
    expect(setQuantity([{ product_id: 1, quantity: 2 }], 1, 0)).toEqual([]);
    expect(removeItem([{ product_id: 1, quantity: 2 }], 1)).toEqual([]);
  });

  it("recovers from corrupt, foreign or hand-edited storage", () => {
    expect(readCart(null)).toEqual({ version: 1, items: [] });
    expect(readCart("not json at all")).toEqual({ version: 1, items: [] });
    expect(readCart(JSON.stringify({ version: 99, items: [{ product_id: 1, quantity: 1 }] })))
      .toEqual({ version: 1, items: [] });
    expect(readCart(JSON.stringify({ version: 1, items: "nope" }))).toEqual({ version: 1, items: [] });
    // Invalid rows are dropped, valid ones survive, and a duplicate product keeps its first line.
    const repaired = readCart(JSON.stringify({
      version: 1,
      items: [
        { product_id: 3, quantity: 2 },
        { product_id: 3, quantity: 5 },
        { product_id: -1, quantity: 1 },
        { product_id: 4, quantity: 0 },
        { product_id: 5, quantity: 1.5 },
        { product_id: "six", quantity: 1 },
        { product_id: 8, quantity: 4 },
      ],
    }));
    expect(repaired.items).toEqual([{ product_id: 3, quantity: 2 }, { product_id: 8, quantity: 4 }]);
  });

  it("round-trips what it writes", () => {
    const state = { version: 1 as const, items: [{ product_id: 2, quantity: 3 }] };
    expect(readCart(writeCart(state))).toEqual(state);
  });
});

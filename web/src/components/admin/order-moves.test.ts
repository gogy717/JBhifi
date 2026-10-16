import { describe, expect, it } from "vitest";

import { MOVES, nextMove } from "./order-moves";

describe("nextMove", () => {
  it("follows_each_path_to_the_customer", () => {
    expect(nextMove("paid", "click_collect")).toBe("picking");
    expect(nextMove("picking", "click_collect")).toBe("ready");
    expect(nextMove("ready", "click_collect")).toBe("collected");
    expect(nextMove("picking", "delivery")).toBe("shipped");
    expect(nextMove("shipped", "delivery")).toBe("delivered");
  });

  it("has_nothing_left_for_a_finished_or_cancelled_order", () => {
    for (const status of ["collected", "delivered", "cancelled", "placed"]) {
      expect(nextMove(status, "delivery")).toBeUndefined();
    }
  });

  it("names_the_move_as_the_order_page_button_does", () => {
    expect(MOVES[nextMove("paid", "delivery")!]).toBe("Start picking");
  });
});

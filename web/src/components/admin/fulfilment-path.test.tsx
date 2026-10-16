import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FulfilmentPath } from "./fulfilment-path";

// What each step says (its circle's number or tick is decorative, hidden from screen readers).
const steps = () => screen.getAllByRole("listitem").map((step) => step.lastElementChild?.textContent);
const current = () => screen.getAllByRole("listitem").find((step) => step.getAttribute("aria-current") === "step");

describe("FulfilmentPath", () => {
  it("click_and_collect_ends_with_collection_and_marks_the_current_step", () => {
    render(<FulfilmentPath method="click_collect" status="picking" reached={["placed", "paid", "picking"]} />);
    expect(steps()).toEqual(["Paid, done", "Being picked, now", "Ready to collect, to come", "Collected, to come"]);
    expect(current()).toHaveTextContent("Being picked");
  });

  it("delivery_ends_with_shipping_and_delivery", () => {
    render(<FulfilmentPath method="delivery" status="shipped" reached={["placed", "paid", "picking", "shipped"]} />);
    expect(steps()).toEqual(["Paid, done", "Being picked, done", "Shipped, now", "Delivered, to come"]);
  });

  it("a_cancelled_order_shows_how_far_it_got_then_cancelled", () => {
    render(<FulfilmentPath method="click_collect" status="cancelled" reached={["placed", "paid", "cancelled"]} />);
    expect(steps()).toEqual(["Paid, done", "Being picked, not reached", "Ready to collect, not reached",
      "Collected, not reached", "Cancelled, now"]);
    expect(current()).toHaveTextContent("Cancelled");
  });
});

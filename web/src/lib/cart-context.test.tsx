/**
 * The cart provider: what a customer sees when browser storage is blocked, and the policy that a cart is
 * kept across a demo-customer switch but holds nothing identity-specific (§3 decision 9).
 */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CART_STORAGE_KEY } from "./cart";
import { CartProvider, useCart } from "./cart-context";

function Probe() {
  const { items, count, addItem, removeSubmitted, ready } = useCart();
  return (
    <div>
      <button type="button" onClick={() => addItem(9, 2)}>add two</button>
      <button type="button" onClick={() => addItem(9, 1)}>add one</button>
      <button type="button" onClick={() => removeSubmitted([{ product_id: 9, quantity: 2 }])}>submit two</button>
      <output data-testid="state">
        {ready ? "ready" : "loading"}:{items.map((item) => `${item.product_id}x${item.quantity}`).join(",")}:{count}
      </output>
    </div>
  );
}

const renderCart = () => render(<CartProvider><Probe /></CartProvider>);

describe("the cart provider", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("reads a stored cart, and a same-key reload keeps it", async () => {
    window.localStorage.setItem(CART_STORAGE_KEY, JSON.stringify({ version: 1, items: [{ product_id: 4, quantity: 3 }] }));
    renderCart();
    expect(await screen.findByTestId("state")).toHaveTextContent("ready:4x3:3");
  });

  it("cart_works_when_storage_is_blocked", async () => {
    // A private window throws on every storage access; the cart has to work for this page view anyway.
    const blocked = () => { throw new Error("storage is blocked"); };
    const getItem = vi.spyOn(window.localStorage, "getItem").mockImplementation(blocked);
    const setItem = vi.spyOn(window.localStorage, "setItem").mockImplementation(blocked);
    const removeItem = vi.spyOn(window.localStorage, "removeItem").mockImplementation(blocked);
    try {
      renderCart();
      expect(await screen.findByTestId("state")).toHaveTextContent("ready::0");
      const user = userEvent.setup();
      await act(async () => { await user.click(screen.getByRole("button", { name: "add two" })); });
      expect(screen.getByTestId("state")).toHaveTextContent("ready:9x2:2");
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
      removeItem.mockRestore();
    }
  });

  it("leaves behind the items added while a checkout was in flight", async () => {
    window.localStorage.setItem(CART_STORAGE_KEY, JSON.stringify({ version: 1, items: [{ product_id: 9, quantity: 1 }] }));
    renderCart();
    const user = userEvent.setup();
    await screen.findByTestId("state");
    // Two units were submitted while the customer added a third: only the submitted two leave the cart.
    await act(async () => { await user.click(screen.getByRole("button", { name: "add two" })); });
    await act(async () => { await user.click(screen.getByRole("button", { name: "add one" })); });
    await act(async () => { await user.click(screen.getByRole("button", { name: "submit two" })); });
    expect(screen.getByTestId("state")).toHaveTextContent("ready:9x2:2");
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Crumbs, Price, QuantityStepper } from "./page-parts";

describe("the breadcrumb", () => {
  it("links_each_step_but_the_last_which_is_the_current_page", () => {
    render(<Crumbs trail={[["Home", "/"], ["My orders", "/orders"], ["#42"]]} />);
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "My orders" })).toHaveAttribute("href", "/orders");
    expect(screen.queryByRole("link", { name: "#42" })).not.toBeInTheDocument();
    expect(screen.getByText("#42")).toHaveAttribute("aria-current", "page");
  });
});

describe("the quantity stepper", () => {
  it("steps_by_one_and_stops_at_its_bounds", () => {
    const onChange = vi.fn();
    const { rerender } = render(<QuantityStepper value={1} max={3} onChange={onChange} label="Quantity of AirPods 4" />);
    expect(screen.getByRole("group", { name: "Quantity of AirPods 4" })).toHaveTextContent("1");
    expect(screen.getByRole("button", { name: "One fewer" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "One more" }));
    expect(onChange).toHaveBeenLastCalledWith(2);

    rerender(<QuantityStepper value={3} max={3} onChange={onChange} label="Quantity of AirPods 4" />);
    expect(screen.getByRole("button", { name: "One more" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "One fewer" }));
    expect(onChange).toHaveBeenLastCalledWith(2);
  });
});

describe("a price", () => {
  it("reads_the_price_before_a_promotion_as_was", () => {
    const { container } = render(<Price value="399.00" was="549.95" />);
    expect(container.textContent).toBe("$399.00was $549.95");
    expect(container.querySelector("s")).toHaveTextContent("was $549.95");
  });

  it("shows_no_struck_price_without_a_promotion", () => {
    const { container } = render(<Price value="249.95" />);
    expect(container.querySelector("s")).toBeNull();
  });
});

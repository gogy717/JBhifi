import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";

import { Button, ErrorBox, Modal, StockBadge } from "./ui";

describe("StockBadge", () => {
  // Colour is never the only signal: every state has words a screen reader reads out.
  it("in_stock_shows_the_count_and_says_in_stock", () => {
    render(<StockBadge quantity={12} />);
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("in stock")).toHaveClass("sr-only");
  });

  it("three_or_fewer_is_low_stock", () => {
    render(<StockBadge quantity={3} />);
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("low stock")).toHaveClass("sr-only");
  });

  it("none_says_out_of_stock_in_words", () => {
    render(<StockBadge quantity={0} />);
    expect(screen.getByText("Out of stock")).toBeVisible();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
});

describe("ErrorBox", () => {
  // The demo's evidence: which database rule refused the request.
  it("a_rule_error_names_the_database_and_the_constraint", () => {
    render(<ErrorBox error={new ApiError(409, "br03_inventory_qty_nonneg", "Not enough stock.")} />);
    const box = screen.getByRole("alert");
    expect(box).toHaveTextContent("Rejected by the database");
    expect(box).toHaveTextContent("Not enough stock.");
    expect(box).toHaveTextContent("br03_inventory_qty_nonneg");
  });

  it("any_other_failure_is_a_failed_request", () => {
    render(<ErrorBox error={new ApiError(0, "network_error", "The API isn't answering.")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Request failed");
  });

  it("can_be_dismissed_when_it_offers_to", () => {
    const onClose = vi.fn();
    render(<ErrorBox error={new ApiError(0, "network_error", "No.")} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe("Button", () => {
  it("is_a_plain_button_unless_told_otherwise_so_it_never_submits_a_form_by_accident", () => {
    render(<Button tone="brand">Change store</Button>);
    expect(screen.getByRole("button", { name: "Change store" })).toHaveAttribute("type", "button");
  });
});

describe("Modal", () => {
  it("is_a_named_dialog_that_escape_closes", () => {
    const onClose = vi.fn();
    render(<Modal title="Cancel order #42?" onClose={onClose}>Sure?</Modal>);
    expect(screen.getByRole("dialog", { name: "Cancel order #42?" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });
});

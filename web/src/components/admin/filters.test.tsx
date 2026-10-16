import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CountTiles, FilterPills } from "./filters";

describe("FilterPills", () => {
  it("says_which_choice_is_on_and_reports_a_new_one", () => {
    const onChange = vi.fn();
    render(<FilterPills label="Sales in the last" value={30} onChange={onChange}
      options={[{ value: 7, label: "7 days" }, { value: 30, label: "30 days" }]} />);
    expect(screen.getByRole("group", { name: "Sales in the last" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "7 days" }));
    expect(onChange).toHaveBeenCalledWith(7);
  });
});

describe("CountTiles", () => {
  const tiles = [
    { key: "paid", label: "To pick", count: 5, attention: true },
    { key: "shipped", label: "Shipped", count: 0, attention: true },
    { key: "ready", label: "Ready to collect" },
  ];

  it("shows_each_count_and_a_dash_while_it_loads", () => {
    render(<CountTiles label="Waiting" tiles={tiles} onSelect={() => {}} />);
    expect(screen.getByRole("button", { name: /To pick/ })).toHaveTextContent("5");
    expect(screen.getByRole("button", { name: /Shipped/ })).toHaveTextContent("0");
    expect(screen.getByRole("button", { name: /Ready to collect/ })).toHaveTextContent("–");
  });

  it("marks_waiting_work_in_orange_only_when_there_is_some", () => {
    render(<CountTiles label="Waiting" tiles={tiles} onSelect={() => {}} />);
    expect(screen.getByText("5")).toHaveClass("text-warn-ink");
    expect(screen.getByText("0")).not.toHaveClass("text-warn-ink");
  });

  it("each_tile_filters_and_the_chosen_one_is_pressed", () => {
    const onSelect = vi.fn();
    render(<CountTiles label="Waiting" tiles={tiles} selected="paid" onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: /To pick/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: /Shipped/ }));
    expect(onSelect).toHaveBeenCalledWith("shipped");
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReturnProgress } from "./return-progress";

const steps = () => screen.getAllByRole("listitem").map((step) => step.textContent);
const current = () => screen.getAllByRole("listitem").find((step) => step.getAttribute("aria-current") === "step")
  ?.textContent;

describe("a return's progress", () => {
  it("marks_where_the_return_is_now", () => {
    const { rerender } = render(<ReturnProgress status="requested" />);
    expect(steps()).toEqual(["Asked for", "Received", "Refunded"]);
    expect(current()).toBe("Asked for");
    rerender(<ReturnProgress status="received" />);
    expect(current()).toBe("Received");
    rerender(<ReturnProgress status="refunded" />);
    expect(current()).toBe("Refunded");
  });

  it("ends_a_rejected_return_at_the_store", () => {
    // A store rejects a return only after receiving it (return_request_status_transition).
    render(<ReturnProgress status="rejected" />);
    expect(steps()).toEqual(["Asked for", "Rejected", "Refunded"]);
    expect(current()).toBe("Rejected");
  });
});

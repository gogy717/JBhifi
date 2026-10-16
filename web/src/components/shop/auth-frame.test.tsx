import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuthFrame } from "./auth-frame";

describe("the sign-in and sign-up frame", () => {
  it("leaves_the_pages_h1_to_clerks_box_and_links_home", () => {
    // Clerk's box renders the page's h1 ("Sign in to …"), so the brand panel's title is an h2.
    render(<AuthFrame title="Welcome back."><h1>Sign in</h1></AuthFrame>);
    expect(screen.getByRole("heading", { level: 2, name: "Welcome back." })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 }).map((h) => h.textContent)).toEqual(["Sign in"]);
    expect(screen.getByRole("link", { name: "TechLight home" })).toHaveAttribute("href", "/");
  });

  it("says_the_store_is_fictional_and_payments_simulated", () => {
    render(<AuthFrame title="Make it yours."><div /></AuthFrame>);
    expect(screen.getByText(/fictional store .* Payments are simulated\./)).toBeInTheDocument();
  });
});

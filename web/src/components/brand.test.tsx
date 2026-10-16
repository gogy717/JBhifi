import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LogoMark, Wordmark } from "./brand";

const SRC = join(__dirname, "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx|css)$/.test(entry.name) ? [path] : [];
  });
}

describe("the TechLight brand", () => {
  it("the_wordmark_reads_TechLight_with_Light_in_the_brand_colour", () => {
    const { container } = render(<Wordmark />);
    expect(container.textContent).toBe("TechLight");
    const light = [...container.querySelectorAll("span")].find((span) => span.textContent === "Light");
    expect(light).toHaveClass("text-brand");
  });

  it("the_mark_is_decorative_so_the_link_around_it_carries_the_name", () => {
    const { container } = render(<LogoMark />);
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  // What a visitor reads: titles, copy, the logo. The lowercase "jb.shop.*" storage keys are internal, and renaming
  // them would empty every browser's saved cart.
  it("no_page_or_component_still_names_the_old_brand", () => {
    const named = sourceFiles(SRC)
      .filter((path) => {
        const text = readFileSync(path, "utf-8");
        return /\bJB\b/.test(text) || /hi-?fi/i.test(text);
      })
      .map((path) => relative(SRC, path));
    expect(named).toEqual([]);
  });
});

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// For component tests: one DOM per test. React Testing Library mounts into document.body, and a tree left
// behind would answer a later test's queries. (Vitest has no global afterEach, so RTL can't register this.)
afterEach(() => {
  cleanup();
});

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// One DOM per test: React Testing Library mounts into document.body, and a leftover tree would answer
// a later query.
afterEach(() => {
  cleanup();
});

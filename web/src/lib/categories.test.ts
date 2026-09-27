import { describe, expect, it } from "vitest";

import type { Category } from "@/lib/api/client";
import { categoryOptions, descendantIds, productCountsByCategory, rootCategories } from "./categories";

const category = (category_id: number, name: string, parent_id: number | null): Category => ({
  category_id, name, parent_id, parent_name: null,
});

// A leaf on its own, a two-level branch, and a three-level branch.
const TREE: Category[] = [
  category(1, "Audio", null),
  category(2, "Headphones", 1),
  category(3, "In-ear", 2),
  category(4, "Computing", null),
  category(5, "Laptops", 4),
  category(6, "Gaming", null),
];

describe("the category tree", () => {
  it("treats a root with no children as a selectable leaf", () => {
    expect(rootCategories(TREE).map((c) => c.name)).toEqual(["Audio", "Computing", "Gaming"]);
    expect(categoryOptions(TREE, true).map((option) => option.id)).toEqual([3, 5, 6]);
  });

  it("includes grandchildren when a branch is filtered", () => {
    expect(descendantIds(TREE, 1).sort()).toEqual([1, 2, 3]);
    expect(descendantIds(TREE, 5)).toEqual([5]);
  });

  it("offers every level, indented, with the depth", () => {
    expect(categoryOptions(TREE).map(({ id, depth }) => [id, depth]))
      .toEqual([[1, 0], [2, 1], [3, 2], [4, 0], [5, 1], [6, 0]]);
  });

  it("terminates safely on a malformed cycle without duplicating options", () => {
    const looped = [...TREE, category(7, "Loop A", 8), category(8, "Loop B", 7)];
    expect(descendantIds(looped, 7).sort()).toEqual([7, 8]);
    const ids = categoryOptions(looped).map((option) => option.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toContain(8);
  });

  it("counts products at every level", () => {
    const counts = productCountsByCategory(TREE, [3, 3, 5, 1]);
    expect(counts.get(3)).toBe(2);
    expect(counts.get(2)).toBe(2);          // the grandchild's products count towards its parent
    expect(counts.get(1)).toBe(3);          // and towards the root, plus its own
    expect(counts.get(6)).toBe(0);
  });
});

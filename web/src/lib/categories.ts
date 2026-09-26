import type { Category } from "@/lib/api/client";

/**
 * The category tree, walked safely.

 * The database refuses a parent change that would create a loop (`category_no_cycle`), but a screen must
 * not hang if it is ever handed one, so every walk here tracks what it has already seen.
 */

export type CategoryOption = { id: number; label: string; depth: number };

function childrenOf(categories: Category[], parentId: number | null): Category[] {
  return categories.filter((category) => category.parent_id === parentId);
}

/** The root categories, in the order the API returned them. */
export function rootCategories(categories: Category[]): Category[] {
  return childrenOf(categories, null);
}

/** `rootId` and every category beneath it, in tree order. */
export function descendantIds(categories: Category[], rootId: number): number[] {
  const byParent = new Map<number | null, Category[]>();
  for (const category of categories) {
    const siblings = byParent.get(category.parent_id) ?? [];
    siblings.push(category);
    byParent.set(category.parent_id, siblings);
  }
  const found: number[] = [];
  const seen = new Set<number>();
  const walk = (id: number) => {
    if (seen.has(id)) return;
    seen.add(id);
    found.push(id);
    for (const child of byParent.get(id) ?? []) walk(child.category_id);
  };
  walk(rootId);
  return found;
}

/** Options for a select, indented by depth. `leavesOnly` keeps the deepest selectable choices. */
export function categoryOptions(categories: Category[], leavesOnly = false): CategoryOption[] {
  const options: CategoryOption[] = [];
  const seen = new Set<number>();
  const walk = (category: Category, depth: number) => {
    if (seen.has(category.category_id)) return;
    seen.add(category.category_id);
    const children = childrenOf(categories, category.category_id);
    if (!leavesOnly || children.length === 0) {
      options.push({ id: category.category_id, label: category.name, depth });
    }
    for (const child of children) walk(child, depth + 1);
  };
  for (const root of rootCategories(categories)) walk(root, 0);
  // Anything whose parent is missing from the list is still offered, rather than disappearing.
  for (const category of categories) {
    if (!seen.has(category.category_id) && category.parent_id !== null) walk(category, 0);
  }
  return options;
}

/** How many products sit at or below each category, for the home page's counts. */
export function productCountsByCategory(categories: Category[], productCategoryIds: number[]): Map<number, number> {
  const direct = new Map<number, number>();
  for (const id of productCategoryIds) direct.set(id, (direct.get(id) ?? 0) + 1);
  const totals = new Map<number, number>();
  for (const category of categories) {
    const total = descendantIds(categories, category.category_id)
      .reduce((sum, id) => sum + (direct.get(id) ?? 0), 0);
    totals.set(category.category_id, total);
  }
  return totals;
}

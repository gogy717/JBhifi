import type { ReactNode } from "react";

import type { Category } from "@/lib/api/client";

// The database has no product photos, so a product's picture slot is a sand tile with its category's line icon and
// its brand: never a made-up photo, an image from elsewhere or a real brand's logo. The five icons are the homepage
// design's, one per top-level category of the seeded tree; anything else gets a generic box.

const ICONS: Record<string, ReactNode> = {
  "Audio": (
    <>
      <path d="M4 16v-4a8 8 0 0 1 16 0v4" />
      <rect x="3" y="14" width="4" height="7" rx="1.5" />
      <rect x="17" y="14" width="4" height="7" rx="1.5" />
    </>
  ),
  "Computers & Tablets": (
    <>
      <rect x="4" y="4" width="16" height="11" rx="1.5" />
      <path d="M2 19h20" />
    </>
  ),
  "Gaming": (
    <>
      <path d="M7 8h10a5 5 0 0 1 5 5v1a3 3 0 0 1-5.4 1.8L15 14H9l-1.6 1.8A3 3 0 0 1 2 14v-1a5 5 0 0 1 5-5z" />
      <path d="M7 11v3M5.5 12.5h3" />
      <circle cx="16.5" cy="12" r="0.6" />
    </>
  ),
  "Phones & Wearables": (
    <>
      <rect x="6" y="2.5" width="12" height="19" rx="2.5" />
      <path d="M11 18.5h2" />
    </>
  ),
  "TV & Home Theatre": (
    <>
      <rect x="2.5" y="4" width="19" height="12.5" rx="1.5" />
      <path d="M8 20.5h8M12 16.5v4" />
    </>
  ),
};

const GENERIC = (
  <>
    <path d="M20 7l-8-4-8 4v10l8 4 8-4z" />
    <path d="M4 7l8 4 8-4" />
    <path d="M12 11v10" />
  </>
);

/** The top-level category a category sits under (itself if it has no parent). Products hang on the leaves of the
 *  tree, so this walks up through parent_id. An unknown id, a missing parent or a cycle gives undefined. */
export function topLevelCategory(categoryId: number | null | undefined, categories: Category[]): Category | undefined {
  const byId = new Map(categories.map((c) => [c.category_id, c]));
  let current = categoryId === null || categoryId === undefined ? undefined : byId.get(categoryId);
  const seen = new Set<number>();
  while (current && current.parent_id !== null) {
    if (seen.has(current.category_id)) return undefined;
    seen.add(current.category_id);
    current = byId.get(current.parent_id);
  }
  return current;
}

/** The line icon of a category's top-level category, drawn in currentColor. Decorative (aria-hidden). */
export function CategoryIcon({ categoryId, categories, className = "h-7 w-7" }: {
  /** Any category in the tree: a product's leaf category or a top-level one. */
  categoryId?: number | null;
  /** The whole tree, e.g. `categories` from useShop() or GET /api/v1/categories. */
  categories: Category[];
  className?: string;
}) {
  const name = topLevelCategory(categoryId, categories)?.name;
  const icon = name !== undefined && Object.hasOwn(ICONS, name) ? name : "generic";
  return (
    <svg aria-hidden="true" data-icon={icon} viewBox="0 0 24 24" className={`shrink-0 ${className}`} fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      {icon === "generic" ? GENERIC : ICONS[icon]}
    </svg>
  );
}

/** A product's picture slot: a sand tile with its category icon and brand. The drawing is hidden from screen readers
 *  (the card or page names the product); children are laid over it and stay readable, e.g.
 *  `<span className="absolute left-2.5 top-2.5 …">27% OFF</span>`. */
export function ProductImage({
  categoryId, categories, brand, className = "h-44 rounded-tile", iconClassName = "h-12 w-12", children,
}: {
  categoryId?: number | null;
  categories: Category[];
  brand?: string;
  /** The tile's height and corners: `h-44 rounded-tile` in a card; e.g. `h-72 rounded-card` on a product page. */
  className?: string;
  iconClassName?: string;
  children?: ReactNode;
}) {
  return (
    <div className={`relative flex items-center justify-center bg-sand ${className}`}>
      <div aria-hidden="true" className="flex flex-col items-center gap-2.5">
        <CategoryIcon categoryId={categoryId} categories={categories} className={`text-faint ${iconClassName}`} />
        {brand && <span className="text-xs font-bold uppercase tracking-[0.08em] text-muted">{brand}</span>}
      </div>
      {children}
    </div>
  );
}

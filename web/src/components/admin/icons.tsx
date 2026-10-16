// Line icons for the admin, drawn like the homepage design's: a 24px grid, 2px round strokes, no fill. They take
// the text colour (stroke="currentColor") and are decorative: the label next to each one carries its meaning.

import type { ReactNode } from "react";

function Icon({ children, className = "h-5 w-5" }: { children: ReactNode; className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" className={`shrink-0 ${className}`}>
      {children}
    </svg>
  );
}

type IconProps = { className?: string };

/** A parcel: orders to pick and hand over. */
export function OrdersIcon(props: IconProps) {
  return <Icon {...props}><path d="M20 7l-8-4-8 4v10l8 4 8-4z" /><path d="M4 7l8 4 8-4" /><path d="M12 11v10" /></Icon>;
}

/** Shelves: stock at a store. */
export function InventoryIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 21V8l9-5 9 5v13" /><path d="M7 21v-8h10v8" /><path d="M7 17h10" />
    </Icon>
  );
}

/** A price tag: the catalogue. */
export function ProductsIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z" /><circle cx="8" cy="8" r="1.5" />
    </Icon>
  );
}

/** The design's "Deals" bolt: promotions. */
export function PromotionsIcon(props: IconProps) {
  return <Icon {...props}><path d="M13 2L4 14h7l-1 8 9-12h-7z" /></Icon>;
}

/** An arrow coming back: returns. */
export function ReturnsIcon(props: IconProps) {
  return <Icon {...props}><path d="M9 14L4 9l5-5" /><path d="M4 9h11a5 5 0 0 1 0 10h-3" /></Icon>;
}

/** Bars: reports. */
export function ReportsIcon(props: IconProps) {
  return <Icon {...props}><path d="M4 20h16" /><path d="M7 16v-5" /><path d="M12 16V6" /><path d="M17 16v-8" /></Icon>;
}

/** A headset: customer support. */
export function SupportIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 15v-3a8 8 0 0 1 16 0v3" /><rect x="3" y="14" width="4" height="6" rx="1.5" />
      <rect x="17" y="14" width="4" height="6" rx="1.5" /><path d="M19 20a3 3 0 0 1-3 2h-2" />
    </Icon>
  );
}

/** The design's map pin: a store. */
export function StoreIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z" /><circle cx="12" cy="9.5" r="2.5" />
    </Icon>
  );
}

/** A van: home delivery. */
export function DeliveryIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M2 6h12v10H2z" /><path d="M14 10h4l3 3v3h-7" /><circle cx="6.5" cy="17.5" r="1.8" />
      <circle cx="17.5" cy="17.5" r="1.8" />
    </Icon>
  );
}

/** A bag: Click & Collect. */
export function CollectIcon(props: IconProps) {
  return <Icon {...props}><path d="M5 8h14l-1 12H6z" /><path d="M9 8V6a3 3 0 0 1 6 0v2" /></Icon>;
}

export function ArrowLeftIcon(props: IconProps) {
  return <Icon {...props}><path d="M19 12H5" /><path d="M11 6l-6 6 6 6" /></Icon>;
}

export function SearchIcon(props: IconProps) {
  return <Icon {...props}><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></Icon>;
}

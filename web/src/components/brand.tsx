// The TechLight logo, from the brand sheet: a rounded brand-coloured tile with a white "T" and a dot, next to the
// wordmark "Tech" + "Light" (Light in the brand colour), set in Sora 700 with -0.03em tracking. app/icon.svg is the
// same mark.

export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  // Decorative: the link or heading around the logo carries the name.
  return (
    <svg aria-hidden="true" viewBox="0 0 64 64" className={`shrink-0 ${className}`}>
      <rect width="64" height="64" rx="14" className="fill-brand" />
      <rect x="14" y="14" width="36" height="9" rx="4.5" fill="#fff" />
      <rect x="27.5" y="14" width="9" height="26" rx="4.5" fill="#fff" />
      <circle cx="32" cy="49" r="4.5" fill="#fff" />
    </svg>
  );
}

/** "Tech" takes the surrounding text colour: ink on light backgrounds, white on dark ones. */
export function Wordmark({ className = "text-xl" }: { className?: string }) {
  return (
    <span className={`font-display font-bold leading-none tracking-[-0.03em] ${className}`}>
      Tech<span className="text-brand">Light</span>
    </span>
  );
}

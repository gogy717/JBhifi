import type { NextConfig } from "next";

// The browser only ever talks to Next.js. Requests to /api/* are forwarded to FastAPI,
// so both run on one origin and there is no CORS to configure.
const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";
// Where the build and the dev server keep their state. The browser suite points this at its own
// directory (see playwright.config.ts): `next dev` refuses to start twice for one directory, and a
// verification run must not disturb — or be disturbed by — a developer's running storefront.
const DIST_DIR = process.env.NEXT_DIST_DIR ?? ".next";

const nextConfig: NextConfig = {
  distDir: DIST_DIR,
  // The dev server only trusts "localhost" by default; without this, opening http://127.0.0.1:3000
  // blocks the dev scripts and the pages never load their data.
  allowedDevOrigins: ["127.0.0.1"],
  devIndicators: { position: "bottom-right" },   // bottom-left would cover the sidebar's API status
  async rewrites() {
    return [
      { source: "/api/health", destination: `${API_URL}/health` },
      { source: "/api/:path*", destination: `${API_URL}/api/:path*` },
    ];
  },
};

export default nextConfig;

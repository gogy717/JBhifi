import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// An optimistic check only: signed-out visitors to the store admin are sent to sign-in. Who may do what is
// decided by the API (app/auth.py) and the database, never here — the Next.js docs say the same.
const isAdmin = createRouteMatcher(["/admin(.*)"]);

export default clerkMiddleware(async (auth, request) => {
  if (isAdmin(request)) await auth.protect();
});

export const config = {
  matcher: [
    // Skip Next.js internals and static files, unless found in search params.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/:path*",
  ],
};

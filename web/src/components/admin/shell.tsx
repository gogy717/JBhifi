import type { ReactNode } from "react";

import { Sidebar } from "@/components/sidebar";

/** The admin's frame: the ink sidebar, and the page beside it on the canvas (below it on a phone). */
export function AdminShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <Sidebar />
      <main className="min-w-0 flex-1 px-4 pb-12 pt-6 md:px-8 md:pt-8">
        <div className="mx-auto max-w-[1280px]">{children}</div>
      </main>
    </div>
  );
}

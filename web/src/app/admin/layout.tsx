import { AdminSessionProvider } from "@/components/admin/session";
import { StaffSessionBar } from "@/components/admin/session-bar";
import { Sidebar } from "@/components/sidebar";

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <AdminSessionProvider>
      <div className="flex min-h-screen flex-col md:flex-row">
        <Sidebar />
        <main className="min-w-0 flex-1 px-4 py-6 md:px-8 md:py-8">
          <StaffSessionBar />
          {children}
        </main>
      </div>
    </AdminSessionProvider>
  );
}

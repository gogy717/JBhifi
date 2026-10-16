import { AdminShell } from "@/components/admin/shell";
import { StaffGate } from "@/components/admin/staff-gate";

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <StaffGate>
      <AdminShell>{children}</AdminShell>
    </StaffGate>
  );
}

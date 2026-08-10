import { Boxes } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";

export default function ErpPage() {
  return (
    <PageHeader
      title="ERP"
      description="Business operations management — inventory, sales, cash, and orders."
      icon={Boxes}
    />
  );
}

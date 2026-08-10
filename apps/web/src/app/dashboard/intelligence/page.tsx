import { Sparkles } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";

export default function IntelligencePage() {
  return (
    <PageHeader
      title="Market Intelligence"
      description="External signals, trends, and competitor analysis from across the market."
      icon={Sparkles}
    />
  );
}

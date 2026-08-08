import { Bot } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";

export default function AgentsPage() {
  return (
    <PageHeader
      title="AI Agents"
      description="Autonomous intelligence agents that reason across your business and the market."
      icon={Bot}
    />
  );
}

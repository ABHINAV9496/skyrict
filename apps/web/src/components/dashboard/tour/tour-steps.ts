import {
  Boxes,
  Bot,
  LayoutDashboard,
  ListOrdered,
  Settings2,
  Sparkles,
  UserRound,
  Users,
  type LucideIcon,
} from "lucide-react";

export type TourPlacement = "top" | "right" | "bottom" | "left";

export interface TourStep {
  /** Value of the `data-tour` attribute on the element to highlight. */
  target: string;
  icon: LucideIcon;
  title: string;
  description: string;
  placement: TourPlacement;
  /** Show only when the user holds at least one of these roles; omitted = everyone. */
  roles?: string[];
}

export const tourSteps: TourStep[] = [
  {
    target: "nav-overview",
    icon: LayoutDashboard,
    title: "Welcome to Skyrict",
    description:
      "Your business OS. Run your whole company — agents, operations, and insight — from one workspace. Everything you need lives in this sidebar.",
    placement: "right",
  },
  {
    target: "card-agents",
    icon: ListOrdered,
    title: "Pick a module to start",
    description:
      "The Overview is your launchpad. Each card opens a module — this is the first place you'll land every time you sign in.",
    placement: "bottom",
  },
  {
    target: "nav-agents",
    icon: Bot,
    title: "AI Agents",
    description:
      "Autonomous agents that act inside your workspace on the tasks you hand them — always within the permissions you set.",
    placement: "right",
  },
  {
    target: "nav-erp",
    icon: Boxes,
    title: "ERP",
    description:
      "Run every department on the same data: CRM, sales, inventory, finance, and HR — connected so nothing is ever out of sync.",
    placement: "right",
  },
  {
    target: "nav-intelligence",
    icon: Sparkles,
    title: "Intelligence",
    description:
      "Analytics and insight across your workspace, so decisions are backed by data, not guesses.",
    placement: "right",
  },
  {
    target: "nav-members",
    icon: Users,
    title: "Members",
    description:
      "Invite your team and control who can see and do what with roles and permissions.",
    placement: "right",
    roles: ["tenant_owner"],
  },
  {
    target: "nav-settings",
    icon: Settings2,
    title: "Settings",
    description:
      "Manage your profile, security, and workspace preferences from here. Integrations and billing are on the way.",
    placement: "right",
    roles: ["tenant_owner"],
  },
  {
    target: "sidebar-profile",
    icon: UserRound,
    title: "You're all set",
    description:
      "That's the shape of Skyrict. Your account and sign-out live in this corner — and you can replay this tour anytime from the Overview.",
    placement: "right",
  },
];

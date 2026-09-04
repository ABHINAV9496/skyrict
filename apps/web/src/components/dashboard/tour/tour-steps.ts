import {
  Boxes,
  Bot,
  LayoutDashboard,
  Settings2,
  Sparkles,
  UserPlus,
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
      "Your business OS. Run your whole company - agents, operations, and insight - from one workspace. Everything you need lives in this sidebar.",
    placement: "right",
  },
  {
    target: "card-agents",
    icon: Bot,
    title: "AI Agents",
    description:
      "Autonomous agents that act inside your workspace on the tasks you hand them - always within the permissions you set.",
    placement: "bottom",
  },
  {
    target: "card-erp",
    icon: Boxes,
    title: "Business Operations",
    description:
      "Run every department on the same data: CRM, sales, inventory, finance, and HR - connected so nothing is ever out of sync.",
    placement: "bottom",
  },
  {
    target: "card-intelligence",
    icon: Sparkles,
    title: "Market Intelligence",
    description:
      "Market research that turns external signals into decisions - search like you would the web, but for your business.",
    placement: "bottom",
  },
  {
    target: "nav-invite",
    icon: UserPlus,
    title: "Invite team",
    description:
      "Send a link that lets new teammates join your workspace. You control the role they land in.",
    placement: "right",
    roles: ["tenant_owner"],
  },
  {
    target: "nav-members",
    icon: Users,
    title: "Members",
    description:
      "See everyone with access, change their roles, and log suspicious devices out.",
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
      "That's the shape of Skyrict. Your account and sign-out live in this corner - and you can replay this tour anytime from the Overview.",
    placement: "right",
  },
];

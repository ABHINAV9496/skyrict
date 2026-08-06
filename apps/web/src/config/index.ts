export const site = {
  name: "Skyrict",
  tagline: "AI Business Operating System",
  description:
    "Skyrict connects what's happening inside your business with what's happening in the market — and lets AI agents act on the synthesis.",
  url: "https://skyrict.com",
};

export const navLinks = [
  { label: "How it works", href: "/#how-it-works" },
  { label: "The bridge", href: "/#bridge" },
  { label: "Security", href: "/#security" },
];

export interface FooterLink {
  label: string;
  href?: string;
  soon?: boolean;
}

export interface FooterColumn {
  title: string;
  links: FooterLink[];
}

export const footerColumns: FooterColumn[] = [
  {
    title: "Product",
    links: [
      { label: "How it works", href: "/#how-it-works" },
      { label: "The bridge", href: "/#bridge" },
      { label: "Pricing", soon: true },
      { label: "Docs", soon: true },
    ],
  },
  {
    title: "Resources",
    links: [
      { label: "Security", href: "/#security" },
      { label: "Source code", href: "https://github.com/nkswalih/skyrict" },
      { label: "Status", soon: true },
    ],
  },
  {
    title: "Company",
    links: [
      { label: "Create account", href: "/register" },
      { label: "Contact", soon: true },
    ],
  },
];

export const signalSources = [
  "Google Trends",
  "YouTube",
  "Reddit",
  "GitHub",
  "News APIs",
];

export const pillars = [
  {
    index: "01",
    name: "Internal truth",
    description:
      "A deliberately scoped ERP slice — inventory, sales, cash, orders — capturing what's actually happening inside your company. Not a bloated SAP replacement; the ~20% of operations that 80% of SMBs actually use.",
  },
  {
    index: "02",
    name: "External truth",
    description:
      "A global market intelligence engine pulling demand signals, competitor moves, and trends from five real sources — Trends, YouTube, Reddit, GitHub, and news — continuously.",
  },
  {
    index: "03",
    name: "The agent layer",
    description:
      "AI agents reason across both sides at once to answer the question no single tool answers: given what's happening in the market and in your business, what should you do?",
  },
];

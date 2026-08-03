export const onboardingSteps = [
  { index: 1, label: "Account", shortLabel: "Account", href: "/onboarding/register" },
  {
    index: 2,
    label: "Verification",
    shortLabel: "Verify",
    href: "/onboarding/register/verify",
  },
  {
    index: 3,
    label: "Security",
    shortLabel: "Security",
    href: "/onboarding/register/security",
  },
  { index: 4, label: "Plan", shortLabel: "Plan", href: "/onboarding/register/plan" },
  {
    index: 5,
    label: "Organization",
    shortLabel: "Organization",
    href: "/onboarding/register/organization",
  },
] as const;

export type PlanId = "starter" | "professional" | "business" | "enterprise";

export interface Plan {
  id: PlanId;
  name: string;
  tagline: string;
  monthly: number | null;
  annual: number | null;
  users: string;
  aiCredits: string;
  support: string;
  modules: string[];
  highlighted?: boolean;
}

export const plans: Plan[] = [
  {
    id: "starter",
    name: "Starter",
    tagline: "For solo operators testing the signal.",
    monthly: 0,
    annual: 0,
    users: "1 user",
    aiCredits: "500 AI credits / month",
    support: "Community support",
    modules: [
      "Core ERP slice (inventory, sales, cash, orders)",
      "Market intel — 1 signal source",
      "1 agent",
      "Email verification & MFA",
    ],
  },
  {
    id: "professional",
    name: "Professional",
    tagline: "For growing teams running on real demand.",
    monthly: 29,
    annual: 24,
    users: "Up to 5 users",
    aiCredits: "5,000 AI credits / month",
    support: "Email support",
    modules: [
      "Everything in Starter",
      "All 5 market signal sources",
      "5 agents",
      "API access",
    ],
    highlighted: true,
  },
  {
    id: "business",
    name: "Business",
    tagline: "For companies with agents in the loop.",
    monthly: 79,
    annual: 66,
    users: "Up to 20 users",
    aiCredits: "20,000 AI credits / month",
    support: "Priority support",
    modules: [
      "Everything in Professional",
      "Agent autopilot (auto-actions)",
      "Unlimited agents",
      "Advanced permissions",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    tagline: "For organizations that need control.",
    monthly: null,
    annual: null,
    users: "Unlimited users",
    aiCredits: "Custom AI credits",
    support: "Dedicated CSM",
    modules: [
      "Everything in Business",
      "SSO / SAML",
      "Custom data integrations",
      "Dedicated infrastructure",
    ],
  },
];

export const industries = [
  "Technology",
  "E-commerce",
  "Retail & Wholesale",
  "Manufacturing",
  "Food & Beverage",
  "Healthcare",
  "Finance",
  "Education",
  "Logistics & Transportation",
  "Professional Services",
  "Construction",
  "Real Estate",
  "Media & Marketing",
  "Nonprofit",
  "Other",
] as const;

export interface Country {
  name: string;
  code: string;
  dialCode?: string;
}

export const countries: Country[] = [
  { name: "United States", code: "US", dialCode: "1" },
  { name: "Canada", code: "CA", dialCode: "1" },
  { name: "United Kingdom", code: "GB", dialCode: "44" },
  { name: "Australia", code: "AU", dialCode: "61" },
  { name: "New Zealand", code: "NZ", dialCode: "64" },
  { name: "Germany", code: "DE", dialCode: "49" },
  { name: "France", code: "FR", dialCode: "33" },
  { name: "Netherlands", code: "NL", dialCode: "31" },
  { name: "Spain", code: "ES", dialCode: "34" },
  { name: "Italy", code: "IT", dialCode: "39" },
  { name: "Portugal", code: "PT", dialCode: "351" },
  { name: "Belgium", code: "BE", dialCode: "32" },
  { name: "Switzerland", code: "CH", dialCode: "41" },
  { name: "Austria", code: "AT", dialCode: "43" },
  { name: "Sweden", code: "SE", dialCode: "46" },
  { name: "Norway", code: "NO", dialCode: "47" },
  { name: "Denmark", code: "DK", dialCode: "45" },
  { name: "Finland", code: "FI", dialCode: "358" },
  { name: "Ireland", code: "IE", dialCode: "353" },
  { name: "Poland", code: "PL", dialCode: "48" },
  { name: "Czechia", code: "CZ", dialCode: "420" },
  { name: "India", code: "IN", dialCode: "91" },
  { name: "Singapore", code: "SG", dialCode: "65" },
  { name: "Japan", code: "JP", dialCode: "81" },
  { name: "South Korea", code: "KR", dialCode: "82" },
  { name: "China", code: "CN", dialCode: "86" },
  { name: "Hong Kong", code: "HK", dialCode: "852" },
  { name: "Taiwan", code: "TW", dialCode: "886" },
  { name: "Malaysia", code: "MY", dialCode: "60" },
  { name: "Philippines", code: "PH", dialCode: "63" },
  { name: "Indonesia", code: "ID", dialCode: "62" },
  { name: "Thailand", code: "TH", dialCode: "66" },
  { name: "Vietnam", code: "VN", dialCode: "84" },
  { name: "United Arab Emirates", code: "AE", dialCode: "971" },
  { name: "Saudi Arabia", code: "SA", dialCode: "966" },
  { name: "Israel", code: "IL", dialCode: "972" },
  { name: "Turkey", code: "TR", dialCode: "90" },
  { name: "South Africa", code: "ZA", dialCode: "27" },
  { name: "Nigeria", code: "NG", dialCode: "234" },
  { name: "Kenya", code: "KE", dialCode: "254" },
  { name: "Brazil", code: "BR", dialCode: "55" },
  { name: "Mexico", code: "MX", dialCode: "52" },
  { name: "Argentina", code: "AR", dialCode: "54" },
  { name: "Chile", code: "CL", dialCode: "56" },
  { name: "Colombia", code: "CO", dialCode: "57" },
  { name: "Peru", code: "PE", dialCode: "51" },
  { name: "Egypt", code: "EG", dialCode: "20" },
  { name: "Morocco", code: "MA", dialCode: "212" },
  { name: "Ukraine", code: "UA", dialCode: "380" },
  { name: "Romania", code: "RO", dialCode: "40" },
  { name: "Greece", code: "GR", dialCode: "30" },
  { name: "Iceland", code: "IS", dialCode: "354" },
  { name: "Luxembourg", code: "LU", dialCode: "352" },
  { name: "Croatia", code: "HR", dialCode: "385" },
  { name: "Slovenia", code: "SI", dialCode: "386" },
  { name: "Bulgaria", code: "BG", dialCode: "359" },
  { name: "Serbia", code: "RS", dialCode: "381" },
  { name: "Pakistan", code: "PK", dialCode: "92" },
  { name: "Bangladesh", code: "BD", dialCode: "880" },
  { name: "Sri Lanka", code: "LK", dialCode: "94" },
] as const;

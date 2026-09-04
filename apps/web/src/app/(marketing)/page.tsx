import type { Metadata } from "next";

import { Bridge } from "@/components/marketing/sections/bridge";
import { Cta } from "@/components/marketing/sections/cta";
import { Hero } from "@/components/marketing/sections/hero";
import { HowItWorks } from "@/components/marketing/sections/how-it-works";
import { site } from "@/config";

export const metadata: Metadata = {
  title: {
    absolute: `${site.name} AI Business Operating System`,
  },
  description:
    "Skyrict pairs a scoped ERP inventory, sales, cash, orders with live market signals from Google Trends, YouTube, Reddit, GitHub, and news. AI agents read both sides at once and tell you what to do next.",
  alternates: {
    canonical: "/",
  },
};

export default function LandingPage() {
  return (
    <>
      <Hero />
      <HowItWorks />
      <Bridge />
      <Cta />
    </>
  );
}

import { Bridge } from "@/components/marketing/sections/bridge";
import { Cta } from "@/components/marketing/sections/cta";
import { Hero } from "@/components/marketing/sections/hero";
import { HowItWorks } from "@/components/marketing/sections/how-it-works";

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

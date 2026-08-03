import {
  Fingerprint,
  ShieldCheck,
  ShieldEllipsis,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { RevealSection } from "@/components/marketing/reveal-section";
import { Button } from "@/components/ui/button";

const securityFeatures: {
  icon: LucideIcon;
  title: string;
  body: string;
}[] = [
  {
    icon: Fingerprint,
    title: "Argon2id password hashing",
    body: "Passwords are never stored in plain form.",
  },
  {
    icon: ShieldCheck,
    title: "Email verification",
    body: "Accounts stay unverified and limited until confirmed.",
  },
  {
    icon: ShieldEllipsis,
    title: "TOTP multi-factor",
    body: "Authenticator codes and one-time backup codes.",
  },
];

function Cta() {
  return (
    <>
      <section id="security" className="scroll-mt-20">
        <div className="mx-auto w-full max-w-6xl px-6 py-16">
          <RevealSection>
            <div className="mx-auto max-w-2xl text-center">
              <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">
                Security
              </p>
              <h2 className="mt-4 font-display text-3xl font-semibold tracking-tight text-foreground">
                Hardened from the first keystroke.
              </h2>
            </div>
            <div className="mt-12 grid gap-6 sm:grid-cols-3">
              {securityFeatures.map(({ icon: Icon, title, body }) => (
                <div key={title} className="rounded-2xl border border-border bg-card p-6">
                  <span className="flex size-10 items-center justify-center rounded-lg bg-primary/15 text-primary">
                    <Icon aria-hidden="true" className="size-5" />
                  </span>
                  <h3 className="mt-4 font-display text-base font-semibold text-foreground">
                    {title}
                  </h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                    {body}
                  </p>
                </div>
              ))}
            </div>
          </RevealSection>
        </div>
      </section>
      <section>
        <div className="mx-auto w-full max-w-6xl px-6 pb-24">
          <RevealSection>
            <div className="relative overflow-hidden rounded-3xl border border-primary/40 bg-[#0a2f3e] px-8 py-16 text-center text-[#f4fafd] sm:py-20">
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-0"
                style={{
                  background: "radial-gradient(55% 60% at 50% 0%, rgba(135,206,235,0.25), transparent 70%)",
                }}
              />
              <div className="relative mx-auto max-w-2xl space-y-6">
                <p className="font-mono text-xs uppercase tracking-[0.2em] text-[#87ceeb]">
                  Get started
                </p>
                <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
                  Connect your operations to the market.
                </h2>
                <p className="text-base leading-relaxed text-[#aedef1]/90">
                  Sign up, wire your ERP slice, and let agents surface what the
                  market is telling you to do.
                </p>
                <div className="flex flex-col items-center justify-center gap-3 pt-2 sm:flex-row">
                  <Button
                    size="lg"
                    className="bg-[#87ceeb] text-[#0a2f3e] hover:bg-[#4cb6e1]"
                    asChild
                  >
                    <Link href="/onboarding/register">Create your account</Link>
                  </Button>
                  <Button
                    variant="outline"
                    size="lg"
                    className="border-[#114f68] bg-transparent text-[#f4fafd] hover:bg-[#114f68]/40 hover:text-[#f4fafd]"
                    asChild
                  >
                    <Link href="/auth/login">Log in</Link>
                  </Button>
                </div>
              </div>
            </div>
          </RevealSection>
        </div>
      </section>
    </>
  );
}

export { Cta };

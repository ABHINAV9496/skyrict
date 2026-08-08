export default function TermsPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">
          Legal
        </p>
        <h1 className="font-display text-2xl font-semibold text-foreground">
          Terms of Service
        </h1>
        <p className="text-sm text-muted-foreground">
          Last updated: August 2026
        </p>
      </div>

      <div className="space-y-4 text-sm leading-relaxed text-muted-foreground">
        <section className="space-y-1">
          <h2 className="text-sm font-semibold text-foreground">
            1. Your agreement
          </h2>
          <p>
            By creating an account or using the Skyrict platform, you agree to
            these terms. If you use Skyrict on behalf of an organization, you
            confirm you are authorized to bind that organization to them.
          </p>
        </section>

        <section className="space-y-1">
          <h2 className="text-sm font-semibold text-foreground">
            2. Your account
          </h2>
          <p>
            You are responsible for safeguarding your credentials and for all
            activity that occurs under your account. Notify us promptly if you
            believe your account has been compromised.
          </p>
        </section>

        <section className="space-y-1">
          <h2 className="text-sm font-semibold text-foreground">
            3. Acceptable use
          </h2>
          <p>
            You may not misuse the service, interfere with its operation, or
            use it in violation of applicable law. We may suspend access to
            accounts that violate these terms.
          </p>
        </section>

        <section className="space-y-1">
          <h2 className="text-sm font-semibold text-foreground">
            4. Changes to these terms
          </h2>
          <p>
            We may update these terms from time to time. Material changes will
            be communicated through the platform, and continued use after
            changes take effect constitutes acceptance.
          </p>
        </section>
      </div>
    </div>
  );
}

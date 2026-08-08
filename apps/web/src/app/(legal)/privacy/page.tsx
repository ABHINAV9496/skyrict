export default function PrivacyPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">
          Legal
        </p>
        <h1 className="font-display text-2xl font-semibold text-foreground">
          Privacy Policy
        </h1>
        <p className="text-sm text-muted-foreground">
          Last updated: August 2026
        </p>
      </div>

      <div className="space-y-4 text-sm leading-relaxed text-muted-foreground">
        <section className="space-y-1">
          <h2 className="text-sm font-semibold text-foreground">
            1. Information we collect
          </h2>
          <p>
            We collect information you provide when you create an account,
            such as your name, email address, and authentication details, along
            with information generated through your use of the platform.
          </p>
        </section>

        <section className="space-y-1">
          <h2 className="text-sm font-semibold text-foreground">
            2. How we use information
          </h2>
          <p>
            We use this information to operate and secure the platform, to
            provide support, and to keep the service running reliably. We do
            not sell your personal information.
          </p>
        </section>

        <section className="space-y-1">
          <h2 className="text-sm font-semibold text-foreground">
            3. Data security
          </h2>
          <p>
            We use industry-standard safeguards to protect your data in transit
            and at rest. No method of transmission or storage is completely
            secure, and we cannot guarantee absolute security.
          </p>
        </section>

        <section className="space-y-1">
          <h2 className="text-sm font-semibold text-foreground">
            4. Your rights
          </h2>
          <p>
            You can request access to, correction of, or deletion of your
            personal information at any time by contacting us through the
            platform. We respond to such requests within applicable timeframes.
          </p>
        </section>
      </div>
    </div>
  );
}

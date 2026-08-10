import type { Metadata } from "next";

import { Footer } from "@/components/marketing/footer";
import { Glows } from "@/components/marketing/glows";
import { Header } from "@/components/marketing/header";
import { JsonLd } from "@/components/seo/json-ld";
import { site } from "@/config";

export const metadata: Metadata = {
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-image-preview": "large",
      "max-snippet": -1,
      "max-video-preview": -1,
    },
  },
  alternates: {
    canonical: "/",
  },
};

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const organization = {
    "@context": "https://schema.org",
    "@type": "Organization",
    "@id": `${site.url}/#organization`,
    name: site.name,
    url: site.url,
    description: site.description,
    sameAs: ["https://github.com/nkswalih/skyrict"],
  };

  const website = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    "@id": `${site.url}/#website`,
    url: site.url,
    name: site.name,
    description: site.description,
    publisher: {
      "@id": `${site.url}/#organization`,
    },
  };

  return (
    <div className="flex min-h-screen flex-col bg-card">
      <JsonLd data={organization} />
      <JsonLd data={website} />
      <Glows />
      <Header />
      <main className="flex-1">{children}</main>
      <Footer />
    </div>
  );
}

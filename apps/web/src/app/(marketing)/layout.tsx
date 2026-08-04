import { Footer } from "@/components/marketing/footer";
import { Glows } from "@/components/marketing/glows";
import { Header } from "@/components/marketing/header";

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-card">
      <Glows />
      <Header />
      <main className="flex-1">{children}</main>
      <Footer />
    </div>
  );
}

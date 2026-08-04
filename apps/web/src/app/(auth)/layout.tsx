import { AuthBrandPanel } from "@/components/auth/auth-brand-panel";
import { Logo } from "@/components/brand/logo";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="relative grid min-h-dvh bg-card lg:h-dvh lg:grid-cols-[minmax(0,5fr)_minmax(0,4fr)] lg:grid-rows-1 lg:overflow-hidden">
      <div className="min-h-0 overflow-hidden">
        <AuthBrandPanel />
      </div>

      <main className="flex min-h-0 flex-col px-6 py-10 lg:overflow-y-auto">
        <div className="flex justify-center lg:hidden">
          <Logo className="text-foreground" />
        </div>

        <div className="mx-auto my-auto flex w-full max-w-sm flex-col py-10">
          {children}
        </div>

        <footer className="mx-auto w-full max-w-sm pb-2 text-center">
          <p className="text-xs text-muted-foreground">
            © {new Date().getFullYear()} Skyrict — AI Business Operating
            System
          </p>
        </footer>
      </main>
    </div>
  );
}

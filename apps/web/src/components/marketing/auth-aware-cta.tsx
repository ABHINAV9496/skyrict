"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useSession } from "@/lib/auth/session";

function AuthAwareCta() {
  const { status } = useSession();

  return (
    <Button size="lg" asChild>
      <Link href={status === "authenticated" ? "/dashboard/agents" : "/register"}>
        {status === "authenticated"
          ? "Open your workspace"
          : "Create your account"}
      </Link>
    </Button>
  );
}

export { AuthAwareCta };

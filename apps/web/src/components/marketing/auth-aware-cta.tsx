"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { demoSessionKey } from "@/config";

function AuthAwareCta() {
  const [hasSession, setHasSession] = useState(false);

  useEffect(() => {
    setHasSession(Boolean(localStorage.getItem(demoSessionKey)));
  }, []);

  return (
    <Button size="lg" asChild>
      <Link href={hasSession ? "/dashboard/agents" : "/onboarding/register"}>
        {hasSession ? "Open your workspace" : "Create your account"}
      </Link>
    </Button>
  );
}

export { AuthAwareCta };

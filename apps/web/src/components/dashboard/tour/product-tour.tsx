"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import { SpotlightOverlay } from "@/components/dashboard/tour/spotlight-overlay";
import { TourTooltip } from "@/components/dashboard/tour/tour-tooltip";
import { tourSteps } from "@/components/dashboard/tour/tour-steps";
import { getMyRoles } from "@/lib/api/identity-api";
import { useSession } from "@/lib/auth/session";

const SEEN_KEY = "skyrict:product-tour-seen";
const START_EVENT = "skyrict:start-tour";
const AUTO_START_DELAY_MS = 600;

/**
 * The workspace home. Middleware serves the Overview at the tenant root `/`
 * (rewritten to the internal `/dashboard`), so both paths are the same page.
 */
const OVERVIEW_PATHS = new Set(["/dashboard", "/"]);

function isOverview(pathname: string): boolean {
  return OVERVIEW_PATHS.has(pathname);
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Dynamic one-by-one product tour. Highlights real dashboard elements with a
 * spotlight overlay and a Floating UI-anchored tooltip.
 *
 * - Auto-starts once per browser (localStorage) on the workspace home, and only
 *   once the user's roles are known.
 * - Role-gated: steps carrying a `roles` list only appear for matching roles
 *   (e.g. Members/Settings are `tenant_owner` only).
 * - Replayable via the `skyrict:start-tour` window event (topbar button).
 * - Falls back to a centered tooltip when the target element is not visible
 *   (e.g. hidden sidebar on small screens).
 */
export function ProductTour() {
  const pathname = usePathname();
  const { status } = useSession();
  const [active, setActive] = useState(false);
  const [pendingStart, setPendingStart] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [referenceEl, setReferenceEl] = useState<HTMLElement | null>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [roles, setRoles] = useState<string[] | null>(null);
  const autoStarted = useRef(false);

  // Steps filtered down to the current user's roles (null roles = still loading).
  const allowedSteps = useMemo(() => {
    const current = roles ?? [];
    return tourSteps.filter(
      (step) => !step.roles || step.roles.some((name) => current.includes(name)),
    );
  }, [roles]);

  const current = allowedSteps[stepIndex];
  const total = allowedSteps.length;

  // Resolve the user's roles once so owner-only steps are shown correctly.
  useEffect(() => {
    if (status !== "authenticated" || roles !== null) return;
    let cancelled = false;
    getMyRoles()
      .then((data) => {
        if (!cancelled) setRoles(data.roles);
      })
      .catch(() => {
        if (!cancelled) setRoles([]);
      });
    return () => {
      cancelled = true;
    };
  }, [status, roles]);

  const finish = useCallback(() => {
    setActive(false);
    setStepIndex(0);
    setPendingStart(false);
    autoStarted.current = true;
    try {
      localStorage.setItem(SEEN_KEY, "true");
    } catch {
      // Storage unavailable (private mode) - tour just closes for this session.
    }
  }, []);

  const start = useCallback(() => {
    if (roles === null || total === 0) {
      setPendingStart(true);
      return;
    }
    if (!isOverview(pathname)) {
      setPendingStart(true);
      return;
    }
    setStepIndex(0);
    setActive(true);
  }, [pathname, roles, total]);

  // Auto-start once per browser on the workspace home. The seen-check runs
  // inside the timeout so dev StrictMode's run → cleanup → run can't cancel it.
  useEffect(() => {
    if (roles === null || !isOverview(pathname)) return;
    const timer = setTimeout(() => {
      if (autoStarted.current) return;
      autoStarted.current = true;
      let seen = false;
      try {
        seen = localStorage.getItem(SEEN_KEY) === "true";
      } catch {
        seen = false;
      }
      if (seen) return;
      start();
    }, AUTO_START_DELAY_MS);
    return () => clearTimeout(timer);
  }, [pathname, roles, start]);

  // Replay from the topbar button (may arrive before navigation completes).
  useEffect(() => {
    const onEvent = () => start();
    window.addEventListener(START_EVENT, onEvent);
    return () => window.removeEventListener(START_EVENT, onEvent);
  }, [start]);

  // Begin a queued start once the user is on the home with roles resolved.
  useEffect(() => {
    if (pendingStart && roles !== null && total > 0 && isOverview(pathname)) {
      setPendingStart(false);
      setStepIndex(0);
      setActive(true);
    }
  }, [pendingStart, pathname, roles, total]);

  // Stop the tour if the user navigates away mid-tour.
  useEffect(() => {
    if (active && !isOverview(pathname)) finish();
  }, [active, pathname, finish]);

  // Resolve the target element and keep its rect in sync with scroll/resize.
  useEffect(() => {
    if (!active) {
      setReferenceEl(null);
      setRect(null);
      return;
    }
    const element = document.querySelector(`[data-tour="${current.target}"]`);
    const target = element instanceof HTMLElement ? element : null;
    setReferenceEl(target);
    const compute = () => {
      setRect(target ? target.getBoundingClientRect() : null);
    };
    compute();
    window.addEventListener("resize", compute);
    window.addEventListener("scroll", compute, true);
    return () => {
      window.removeEventListener("resize", compute);
      window.removeEventListener("scroll", compute, true);
    };
  }, [active, current, stepIndex]);

  // Bring the highlighted element into view before showing the step.
  useEffect(() => {
    if (!active) return;
    const element = document.querySelector(`[data-tour="${current.target}"]`);
    if (element instanceof HTMLElement) {
      element.scrollIntoView({
        block: "nearest",
        behavior: prefersReducedMotion() ? "auto" : "smooth",
      });
    }
  }, [active, stepIndex, current]);

  // Keyboard control: Esc closes, arrow keys step through the tour.
  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        finish();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        setStepIndex((index) => Math.min(index + 1, total - 1));
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        setStepIndex((index) => Math.max(index - 1, 0));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, finish, total]);

  if (!active || total === 0) return null;

  const next = () => {
    if (stepIndex === total - 1) {
      finish();
      return;
    }
    setStepIndex((index) => index + 1);
  };

  const back = () => setStepIndex((index) => Math.max(0, index - 1));

  return (
    <>
      <SpotlightOverlay active={active} rect={rect} />
      <TourTooltip
        key={stepIndex}
        step={current}
        index={stepIndex}
        total={total}
        referenceEl={referenceEl}
        onBack={back}
        onNext={next}
        onClose={finish}
      />
      <p role="status" className="sr-only">
        {`Tour step ${stepIndex + 1} of ${total}: ${current.title}`}
      </p>
    </>
  );
}

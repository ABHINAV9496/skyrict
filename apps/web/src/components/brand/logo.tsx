import { cn } from "@/lib/utils";

function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      role="img"
      aria-label="Skyrict"
      className={cn("size-8", className)}
    >
      <defs>
        <linearGradient id="sky-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#aedef1" />
          <stop offset="100%" stopColor="#4cb6e1" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#sky-mark)" />
      <g stroke="#0a2f3e" strokeWidth="2.6" strokeLinecap="round">
        <path d="M9 22v-4" />
        <path d="M14 22v-8" />
        <path d="M19 22V11" />
        <path d="M24 22v-13" />
      </g>
      <circle cx="24" cy="9" r="2.1" fill="#0a2f3e" stroke="none" />
    </svg>
  );
}

function Logo({
  className,
  wordmark = true,
}: {
  className?: string;
  wordmark?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark className="size-7" />
      {wordmark ? (
        <span className="font-display text-lg font-semibold tracking-tight text-current">
          Skyrict
        </span>
      ) : null}
    </span>
  );
}

export { Logo, LogoMark };

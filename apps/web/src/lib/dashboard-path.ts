/**
 * Convert the browser's pathname to the internal `/dashboard/*` form. The
 * workspace surface serves the dashboard at the tenant root, so the public URL
 * strips the prefix (`/roles`, `/members`) and middleware rewrites it back to
 * `/dashboard/roles` etc. `usePathname()` reports the public path, so
 * normalize before matching.
 */
export function normalizeDashboardPath(pathname: string): string {
  if (pathname === "/") return "/dashboard";
  return pathname.startsWith("/dashboard") ? pathname : `/dashboard${pathname}`;
}

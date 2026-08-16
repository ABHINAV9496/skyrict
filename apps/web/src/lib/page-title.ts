export const knownTitles: Record<string, string> = {
  "/dashboard": "Overview",
  "/dashboard/members": "Members",
  "/dashboard/invite": "Invite team",
  "/dashboard/agents": "AI Agents",
  "/dashboard/erp": "Business Operations",
  "/dashboard/intelligence": "Market Intelligence",
  "/dashboard/settings": "Settings",
  "/dashboard/integrations": "Integrations",
};

const idPattern =
  /^(?:\d+|[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}|[\da-f]{8,})$/i;

function humanize(segment: string): string {
  return segment
    .replace(/[-_]+/g, " ")
    .replace(/([a-z\d])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .trim();
}

/** Resolve a page title from any workspace route, known or not. */
export function resolvePageTitle(pathname: string): string {
  const normalized =
    pathname === "/"
      ? "/dashboard"
      : pathname.startsWith("/dashboard")
        ? pathname
        : `/dashboard${pathname}`;
  if (knownTitles[normalized]) return knownTitles[normalized];

  const segments = normalized.split("/").filter(Boolean);
  const parent = Object.keys(knownTitles)
    .filter((key) => normalized.startsWith(`${key}/`))
    .sort((a, b) => b.length - a.length)[0];

  const rest = parent
    ? segments
        .slice(parent.split("/").filter(Boolean).length)
        .filter((segment) => !idPattern.test(segment))
        .map(humanize)
    : [];

  if (parent && rest.length > 0) return `${knownTitles[parent]} · ${rest.join(" · ")}`;

  const last = [...segments].reverse().find((segment) => !idPattern.test(segment));
  return last ? humanize(last) : "Dashboard";
}

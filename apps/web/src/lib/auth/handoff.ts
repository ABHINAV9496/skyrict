import { getMyRoles } from "@/lib/api/identity-api";

/** Returns `/leave` when the user holds *only* the portal role,
 *  `/` for any other role set, and `/` on error (fail-open). */
export function soleRoleDestination(roles: string[]): string {
  return roles.length === 1 && roles[0] === "employee_self_service"
    ? "/leave"
    : "/";
}

/** Resolve the post-login redirect destination based on the user's
 *  role set.  Logs the resolved value for debugging. */
export async function resolveHandoffDestination(): Promise<string> {
  try {
    const { roles } = await getMyRoles();
    const destination = soleRoleDestination(roles);
    console.debug("[auth] handoff", { roles, destination });
    return destination;
  } catch {
    return "/";
  }
}

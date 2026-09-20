import { ErpOverviewSkeleton } from "@/components/ui/page-skeletons";

/**
 * Route-level fallback for the ERP world.
 *
 * CONTENT ONLY on purpose: `ShellRouter` already mounts `ErpShell` (real
 * sidebar + topbar) around this segment, so a "world" skeleton here paints a
 * second sidebar/topbar over the live chrome. That double chrome is what read
 * as a bug on entry - the fallback must only stand in for the page body.
 */
export default function ErpLoading() {
    return <ErpOverviewSkeleton />;
}

export const PAGE_TITLE_EVENT = "skyrict:page-title";

/**
 * Publish a human-readable title for the current page (e.g. an order number
 * or a customer name). The workspace Topbar listens and appends it to the
 * breadcrumb; pass `null` to clear it.
 */
export function setPageTitle(title: string | null): void {
  window.dispatchEvent(
    new CustomEvent(PAGE_TITLE_EVENT, { detail: { title } }),
  );
}

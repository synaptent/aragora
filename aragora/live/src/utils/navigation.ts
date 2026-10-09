/**
 * Full document load. Unlike router navigation it discards every mounted page,
 * in-memory cache and in-flight request of the current document.
 */
export function hardNavigate(url: string): void {
  window.location.assign(url);
}

/** Reload the current document from the network, discarding its in-memory state. */
export function reloadDocument(): void {
  window.location.reload();
}

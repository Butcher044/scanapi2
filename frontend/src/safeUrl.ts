/**
 * Links shown in the UI come from bank dev portals, not from us. Rendering such
 * a value straight into href would make a `javascript:` or `data:` URL clickable,
 * so every portal link passes through here first.
 */
export function isSafeHttpUrl(url: string): boolean {
  if (!url) return false
  try {
    const { protocol } = new URL(url, window.location.origin)
    return protocol === 'http:' || protocol === 'https:'
  } catch {
    return false  // not a URL at all
  }
}

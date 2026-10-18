/**
 * Canonical origin for SEO (Open Graph, Twitter cards, canonical URLs).
 * Set VITE_SITE_URL in CI/deploy (e.g. https://evecta.io) so previews use production URLs even when testing locally.
 */
export function getSiteOrigin(): string {
  const env = import.meta.env.VITE_SITE_URL as string | undefined;
  if (env?.trim()) {
    return env.replace(/\/$/, '');
  }
  if (typeof window !== 'undefined') {
    return window.location.origin;
  }
  return 'https://evecta.io';
}

export function absoluteUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${getSiteOrigin()}${normalized}`;
}

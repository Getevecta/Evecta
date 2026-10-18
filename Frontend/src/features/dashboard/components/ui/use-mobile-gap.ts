import { useIsMobile } from './use-mobile';

/**
 * Mobile Gap System
 * Maps desktop gaps to mobile-appropriate gaps
 * 
 * Mapping:
 * - Desktop 4-6px → Mobile 4px (Small/tight)
 * - Desktop 8px → Mobile 6px (Small-medium)
 * - Desktop 10-12px → Mobile 8px (Standard mobile spacing - MOST USED)
 * - Desktop 16px → Mobile 12px (Medium spacing)
 * - Desktop 18-24px → Mobile 16px (Large spacing)
 * - Desktop 20-24px → Mobile 20-24px (Extra large - use carefully)
 */

/**
 * Get mobile-appropriate gap value based on desktop gap
 * @param desktopGap - Gap value in pixels (e.g., '8px', '12px', '16px')
 * @param isMobile - Whether current view is mobile
 * @returns Gap value appropriate for the current view
 */
export function getMobileGap(desktopGap: string | number, isMobile: boolean): string {
  if (!isMobile) {
    // Return desktop gap as-is
    return typeof desktopGap === 'number' ? `${desktopGap}px` : desktopGap;
  }

  // Extract numeric value
  const gapValue = typeof desktopGap === 'number' 
    ? desktopGap 
    : parseInt(desktopGap.replace('px', '').trim(), 10);

  // Map desktop gaps to mobile gaps
  if (gapValue <= 6) {
    // Desktop 4-6px → Mobile 4px
    return '4px';
  } else if (gapValue === 8) {
    // Desktop 8px → Mobile 6px
    return '6px';
  } else if (gapValue >= 10 && gapValue <= 12) {
    // Desktop 10-12px → Mobile 8px (MOST USED)
    return '8px';
  } else if (gapValue === 16) {
    // Desktop 16px → Mobile 12px
    return '12px';
  } else if (gapValue >= 18 && gapValue <= 24) {
    // Desktop 18-24px → Mobile 16px
    return '16px';
  } else if (gapValue > 24) {
    // Desktop >24px → Keep as is (use carefully)
    return typeof desktopGap === 'number' ? `${desktopGap}px` : desktopGap;
  }

  // Default: return original gap
  return typeof desktopGap === 'number' ? `${desktopGap}px` : desktopGap;
}

/**
 * Hook to get mobile-appropriate gap value
 * @param desktopGap - Gap value in pixels
 * @returns Gap value appropriate for current view
 */
export function useMobileGap(desktopGap: string | number): string {
  const isMobile = useIsMobile();
  return getMobileGap(desktopGap, isMobile);
}


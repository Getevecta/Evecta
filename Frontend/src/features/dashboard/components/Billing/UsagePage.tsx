import { SpendingSection } from './SpendingSection';
import './BillingPage.css';

/** Settings → Usage: credit usage hero + top-ups (pricing lives on Billing). */
export function UsagePage() {
  return (
    <div className="billing-page billing-page--usage">
      <SpendingSection includeUsageHero />
    </div>
  );
}

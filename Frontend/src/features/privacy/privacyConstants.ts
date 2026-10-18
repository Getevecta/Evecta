// Last updated dates for legal documents
// This file is automatically updated by scripts/updatePrivacyDates.js
// Dates are based on file modification times

export const TERMS_OF_SERVICE_LAST_UPDATED = new Date('2026-06-14');
export const PRIVACY_POLICY_LAST_UPDATED = new Date('2026-06-14');

// Format date as "DD Month YYYY" (e.g., "15 December 2025")
export const formatLastUpdatedDate = (date: Date): string => {
  const months = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
  ];
  
  const day = date.getDate();
  const month = months[date.getMonth()];
  const year = date.getFullYear();
  
  return `${day} ${month} ${year}`;
};

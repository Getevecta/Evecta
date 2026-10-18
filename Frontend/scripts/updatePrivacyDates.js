const fs = require('fs');
const path = require('path');

// Paths to the privacy files
const termsOfServicePath = path.join(__dirname, '../src/features/privacy/TermsOfService.tsx');
const privacyPolicyPath = path.join(__dirname, '../src/features/privacy/PrivacyPolicy.tsx');
const constantsPath = path.join(__dirname, '../src/features/privacy/privacyConstants.ts');

// Get file modification time
function getFileModificationDate(filePath) {
  try {
    const stats = fs.statSync(filePath);
    return stats.mtime; // Last modification time
  } catch (error) {
    console.error(`Error reading file ${filePath}:`, error);
    return new Date(); // Fallback to current date
  }
}

// Format date as "YYYY-MM-DD"
function formatDateForCode(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

// Read current constants file
function updateConstantsFile() {
  const termsDate = getFileModificationDate(termsOfServicePath);
  const privacyDate = getFileModificationDate(privacyPolicyPath);

  const termsFormatted = formatDateForCode(termsDate);
  const privacyFormatted = formatDateForCode(privacyDate);

  const constantsContent = `// Last updated dates for legal documents
// This file is automatically updated by scripts/updatePrivacyDates.js
// Dates are based on file modification times

export const TERMS_OF_SERVICE_LAST_UPDATED = new Date('${termsFormatted}');
export const PRIVACY_POLICY_LAST_UPDATED = new Date('${privacyFormatted}');

// Format date as "DD Month YYYY" (e.g., "15 December 2025")
export const formatLastUpdatedDate = (date: Date): string => {
  const months = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
  ];
  
  const day = date.getDate();
  const month = months[date.getMonth()];
  const year = date.getFullYear();
  
  return \`\${day} \${month} \${year}\`;
};
`;

  fs.writeFileSync(constantsPath, constantsContent, 'utf8');
  console.log('✅ Privacy dates updated successfully!');
  console.log(`   Terms of Service: ${termsFormatted}`);
  console.log(`   Privacy Policy: ${privacyFormatted}`);
}

// Run the update
updateConstantsFile();


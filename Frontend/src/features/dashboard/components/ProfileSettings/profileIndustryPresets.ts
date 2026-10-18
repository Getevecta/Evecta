/**
 * Industry / sector suggestions for “Industry you want to target”.
 * Stored as human-readable strings (value === label). Custom values still allowed in the UI.
 */
const INDUSTRY_LINES = `
Technology
Software
SaaS
Cloud Computing
Cybersecurity
Artificial Intelligence
Machine Learning
Data & Analytics
Internet & Digital Media
E-commerce
Telecommunications
Electronics
Semiconductors
Hardware
Robotics
IoT
Gaming
Healthtech
Biotechnology
Pharmaceuticals
Healthcare
Medical Devices
Mental Health
Dental
Veterinary
Fitness & Wellness
Finance
Banking
Insurance
FinTech
Investment Management
Venture Capital
Accounting
Real Estate
Construction
Architecture
Engineering Services
Manufacturing
Automotive
Aerospace & Defense
Chemicals
Food & Beverage
Agriculture
Retail
Wholesale
Consumer Goods
Fashion & Apparel
Luxury Goods
Hospitality
Restaurants
Travel & Tourism
Education
EdTech
Professional Training
Nonprofit
Government
Legal Services
Consulting
Management Consulting
HR & Staffing
Marketing & Advertising
Public Relations
Media & Entertainment
Publishing
Sports
Energy
Oil & Gas
Renewable Energy
Utilities
Mining
Logistics & Supply Chain
Transportation
Aviation
Maritime
Rail
Environmental Services
Facility Management
Security Services
Cleaning Services
Printing
Packaging
Textiles
Paper & Forest Products
Music & Performing Arts
Photography & Video
Events & Exhibitions
Waste Management
Other
`;

function parsePresetLabels(): string[] {
  const labels = INDUSTRY_LINES.trim()
    .split(/\n/)
    .map((s) => s.trim())
    .filter(Boolean);
  return [...new Set(labels)].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
}

export const PROFILE_INDUSTRY_PRESET_LABELS: readonly string[] = parsePresetLabels();

/** Legacy slug values saved by older versions of the profile form → display label */
export const LEGACY_INDUSTRY_SLUG_TO_LABEL: Readonly<Record<string, string>> = {
  technology: 'Technology',
  healthcare: 'Healthcare',
  finance: 'Finance',
  retail: 'Retail',
  education: 'Education',
  'real-estate': 'Real Estate',
  manufacturing: 'Manufacturing',
  other: 'Other',
};

export function normalizeIndustryValue(stored: string): string {
  const t = stored?.trim() ?? '';
  if (!t) return '';
  const mapped = LEGACY_INDUSTRY_SLUG_TO_LABEL[t.toLowerCase()];
  return mapped ?? t;
}

/**
 * Broad job-title suggestions for the “Your Role” combobox.
 * Users can still type any custom title (allowCustomValue); this list only powers autocomplete.
 */
const ROLE_LINES = `
Chief Executive Officer
Chief Operating Officer
Chief Financial Officer
Chief Technology Officer
Chief Information Officer
Chief Marketing Officer
Chief Product Officer
Chief Human Resources Officer
Chief Revenue Officer
Chief Data Officer
Chief Security Officer
Chief Compliance Officer
Chief Strategy Officer
Chief of Staff
Founder
Co-Founder
CEO/Founder
Owner
President
Managing Director
General Manager
Executive Director
Board Member
Chairperson
Partner
Principal
Vice President
VP of Sales
VP of Marketing
VP of Engineering
VP of Product
VP of Operations
VP of Finance
VP of HR
VP of People
VP of Business Development
Head of Sales
Head of Marketing
Head of Engineering
Head of Product
Head of Design
Head of Operations
Head of Finance
Head of HR
Head of Growth
Head of Data
Head of Customer Success
Director
Director of Sales
Director of Marketing
Director of Engineering
Director of Product
Director of Design
Director of Operations
Director of Finance
Director of HR
Associate Director
Senior Director
Assistant Director
Regional Director
Country Manager
General Sales Manager
Sales Manager
Regional Sales Manager
Account Manager
Senior Account Manager
Key Account Manager
Strategic Account Manager
Enterprise Account Manager
Sales Director
Business Development
Business Development Manager
Business Development Representative
Sales Development Representative
Account Executive
Senior Sales Executive
Inside Sales Representative
Outside Sales Representative
Channel Sales Manager
Partner Manager
Sales Engineer
Solutions Engineer
Pre-Sales Engineer
Customer Success Manager
Implementation Manager
Professional Services Consultant
Account Executive Customer Success
Marketing Manager
Digital Marketing Manager
Growth Marketing Manager
Product Marketing Manager
Brand Manager
Content Marketing Manager
Social Media Manager
SEO Specialist
SEM Specialist
PPC Manager
Marketing Operations Manager
Demand Generation Manager
Field Marketing Manager
Communications Manager
Public Relations Manager
Event Marketing Manager
Marketing Analyst
Marketing Coordinator
Creative Director
Art Director
Copywriter
Content Writer
Technical Writer
Editor
Designer
Graphic Designer
Visual Designer
Digital Designer
Web Designer
UX Designer
UI Designer
Product Designer
Interaction Designer
User Researcher
UX Researcher
UX Writer
Design Lead
Design Director
Product Manager
Senior Product Manager
Group Product Manager
Technical Product Manager
Product Owner
Program Manager
Project Manager
Senior Project Manager
Technical Program Manager
Scrum Master
Agile Coach
Business Analyst
Senior Business Analyst
Product Analyst
Operations Manager
Operations Analyst
Business Operations Manager
Sales Operations Manager
Revenue Operations Manager
Office Manager
Facilities Manager
Strategy Manager
Management Consultant
Project Coordinator
Team Lead
Engineering Manager
Senior Engineering Manager
Director of Software Engineering
Software Engineer
Senior Software Engineer
Staff Software Engineer
Principal Software Engineer
Frontend Developer
Frontend Engineer
Backend Developer
Backend Engineer
Full Stack Developer
Full Stack Engineer
Mobile Developer
iOS Developer
Android Developer
DevOps Engineer
Site Reliability Engineer
Platform Engineer
Infrastructure Engineer
Cloud Architect
Solutions Architect
Enterprise Architect
Technical Architect
Security Engineer
Application Security Engineer
Site Lead
QA Engineer
Quality Assurance Analyst
Test Automation Engineer
Data Engineer
Machine Learning Engineer
AI Engineer
Data Scientist
Senior Data Scientist
Research Scientist
Database Administrator
Business Intelligence Analyst
Data Analyst
Analytics Manager
Finance Manager
Financial Analyst
Senior Financial Analyst
Controller
Accountant
Tax Manager
Treasury Analyst
FP&A Manager
Investor Relations Manager
Auditor
Internal Auditor
HR Manager
Human Resources Manager
HR Business Partner
People Operations Manager
Talent Acquisition Manager
Recruiter
Technical Recruiter
Learning and Development Manager
Compensation Manager
Legal Counsel
General Counsel
Paralegal
Compliance Manager
Risk Manager
Privacy Officer
Information Security Manager
CISO
IT Manager
IT Director
Systems Administrator
Network Administrator
Help Desk Technician
IT Support Specialist
Software Architect
CRM Manager
ERP Administrator
Procurement Manager
Supply Chain Manager
Logistics Coordinator
Warehouse Manager
Inventory Manager
Manufacturing Manager
Plant Manager
Quality Manager
R&D Manager
Research and Development Director
Pharmacist
Nurse Manager
Medical Practice Manager
Physician
Dentist
Therapist
Counselor
Social Worker
Teacher
Professor
Academic Advisor
School Principal
Administrator
Real Estate Agent
Real Estate Broker
Property Manager
Insurance Agent
Financial Advisor
Wealth Manager
Retail Store Manager
Merchandising Manager
E-commerce Manager
Hospitality Manager
Restaurant Manager
Chef
Construction Manager
Contractor
Electrician
Plumber
Architect Professional
Civil Engineer
Mechanical Engineer
Executive Assistant
Administrative Assistant
Receptionist
Customer Support Specialist
Customer Service Representative
Technical Support Specialist
Call Center Agent
Freelancer
Self-Employed
Consultant
Independent Consultant
Contract Consultant
Trainer
Coach
Photographer
Videographer
Intern
Student
Retiree
Not Currently Employed
Other
`;

function parsePresetLabels(): string[] {
  const labels = ROLE_LINES.trim()
    .split(/\n/)
    .map((s) => s.trim())
    .filter(Boolean);
  return [...new Set(labels)].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
}

export const PROFILE_ROLE_PRESET_LABELS: readonly string[] = parsePresetLabels();

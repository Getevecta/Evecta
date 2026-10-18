import './PrivacyPolicy.css';
import '../homepage/HomePage.css';
import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { HomePageHeader, HomePageFooter } from '../homepage/HomePage';
import { PageSeo } from '../../shared/components/PageSeo/PageSeo';

const SECTIONS = [
  {
    id: 'section-1',
    title: 'Introduction',
    content: [
      'Evecta Inc. ("Evecta", "we", "us" or "our") provides a business-to-business (B2B) software platform that enables companies to discover leads, manage outreach, run campaigns, and view performance analytics. This Privacy Policy describes how Evecta collects, uses, discloses, and protects personal information through our website, products, services, and related interactions (collectively, the "Service").',
      'This policy applies to all individuals whose personal information we process in connection with the Service, including representatives of our business customers.',
      'By accessing or using the Service, you agree to the practices described in this Privacy Policy.',
    ],
  },
  {
    id: 'section-2',
    title: 'What Kind of Information We Collect',
    content: [
      'We collect only the information needed to operate Evecta properly and improve the experience for our users. When you sign up or contact us, we may collect basic information such as your name, work email address, company name, job title, and phone number.',
      'We also collect account-related details like login credentials, workspace settings, and feature preferences so that your account functions correctly and securely.',
      'When you communicate with us through email, chat, or support channels, we store those messages to help resolve issues, provide assistance, and improve our services.',
    ],
  },
  {
    id: 'section-3',
    title: 'Technical and Usage Information',
    content: [
      'When you use Evecta, certain technical data is automatically collected. This includes IP address, browser type, device information, operating system, and general location (such as city or country).',
      'We also track how users interact with the platform (for example, which features are used, how long sessions last, and how users navigate Evecta). This helps us improve performance, identify bugs, and make the product more intuitive.',
      'For outreach and campaign features, Evecta may record non-content signals such as email opens, clicks, bounce status, or response indicators. These signals are used for analytics, scoring, and campaign reporting.',
    ],
  },
  {
    id: 'section-4',
    title: 'Email Accounts, Integrations, and External Data',
    content: [
      'If you connect an email account or third-party service to Evecta, we access only the data required to provide the requested functionality. This may include sending emails, checking inbox, or storing basic account information.',
      'Evecta retrieves and shows Gmail messages and replies to display email conversations within the application. Gmail data is stored securely, encrypted at rest, and deleted when the user disconnects their Gmail account or requests deletion. Evecta does not use Gmail data for advertising, analytics, or machine learning.',
      'Evecta does not read or permanently store private email conversations unless it is necessary to deliver a specific feature. Email credentials are never shared with third parties. Evecta may also use publicly available business information or licensed data sources to support lead discovery. This information is used responsibly and within applicable legal and contractual boundaries.',
      'In most cases, Evecta acts as a data processor on behalf of its customers, who control how outreach data is collected, used, and stored. Customers are responsible for ensuring that their use of the platform complies with applicable privacy and data protection laws.',
      'Customers are responsible for ensuring their outreach activities, including email campaigns, comply with applicable anti-spam, consent, and communication laws in their jurisdiction.',
    ],
  },
  {
    id: 'section-5',
    title: 'How Evecta Uses Personal Information',
    content: [
      'We use personal information to operate and improve Evecta. This includes creating and managing accounts, processing payments, delivering features, providing customer support, and communicating important service updates.',
      'We also analyze platform usage in an aggregated and anonymized way to understand trends, improve system reliability, and develop new tools. This analysis does not identify individual users.',
      'Evecta does not use personal data for unrelated purposes and does not collect more data than is reasonably necessary.',
    ],
  },
  {
    id: 'section-6',
    title: 'AI Features and Responsible Data Use',
    content: [
      'Evecta uses AI-powered features to help users work more efficiently such as generating insights, assisting with drafts, improving targeting or analyzing performance.',
      'However, Evecta does not use your private email content, connected inbox data, or customer communications to train generated AI or machine-learning models.',
      'When Evecta uses third-party APIs such as Google Workspace APIs, we follow their data-use policies, including limited-use requirements. Your data remains yours.',
    ],
  },
  {
    id: 'section-7',
    title: 'How and When We Share Data',
    content: [
      'Evecta does not sell personal information for advertising or consumer profiling.',
      'We share data only with trusted service providers who help us operate the platform, such as cloud hosting, analytics tools, payment processors, and customer support systems. These providers are contractually required to protect your data.',
      'We may also disclose information if required by law, court order, or to protect the rights, safety, and security of Evecta and its Users. In the event of a business transaction (such as a merger or acquisition), relevant data may be transferred as part of that process.',
      'Evecta is designed to support compliance with applicable data protection regulations such as GDPR, CCPA, and similar regional privacy laws, where applicable.',
    ],
  },
  {
    id: 'section-8',
    title: 'Data Retention and Deletion',
    content: [
      'Evecta retains personal information only for as long as it is necessary to provide services, comply with legal requirements, resolve disputes, and maintain security.',
      'When information is no longer required, it is securely deleted, anonymized, or isolated from active systems. Users may request deletion of their personal data, subject to legal or contractual obligations.',
    ],
  },
];

const PrivacyPolicy = () => {
  const [expandedId, setExpandedId] = useState<string | null>(SECTIONS[0]?.id ?? null);

  const toggle = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  return (
    <div className="homepage privacy-page min-h-screen homepage-gradient-bg theme-dark">
      <PageSeo
        title="Privacy Policy"
        description="How Evecta collects, uses, and protects personal information when you use our B2B lead management platform."
        path="/privacy-policy"
      />
      <HomePageHeader isDark />
      <div className="privacy-policy-page">
        <div className="legal-page-layout">
          <div className="legal-page-main">
        <div className="privacy-container">
          <div className="privacy-header">
            <p className="homepage-why-choose-badge text-sm font-medium">Privacy Policy</p>
            <h1 className="homepage-why-choose-heading text-white">Evecta Privacy Policy</h1>
          </div>

          <div className="privacy-main-content privacy-main-content-full">
            <div className="privacy-content">
              {SECTIONS.map((section, index) => {
                const isExpanded = expandedId === section.id;
                return (
                  <section key={section.id} id={section.id} className="privacy-section privacy-section-accordion">
                    <button
                      type="button"
                      className="privacy-section-heading-btn"
                      onClick={() => toggle(section.id)}
                      aria-expanded={isExpanded}
                      aria-controls={`${section.id}-body`}
                    >
                      <span className="privacy-section-title">{index + 1}. {section.title}</span>
                      <ChevronDown className={`privacy-section-chevron ${isExpanded ? 'privacy-section-chevron-expanded' : ''}`} aria-hidden />
                    </button>
                    <div
                      id={`${section.id}-body`}
                      className="privacy-section-body"
                      role="region"
                      aria-hidden={!isExpanded}
                      hidden={!isExpanded}
                    >
                      {section.content.map((paragraph, i) => (
                        <p key={i}>{paragraph}</p>
                      ))}
                    </div>
                  </section>
                );
              })}
            </div>
          </div>
        </div>
          </div>
        </div>
      </div>
      <HomePageFooter />
    </div>
  );
};

export default PrivacyPolicy;

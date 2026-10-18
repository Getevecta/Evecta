import { Helmet } from 'react-helmet-async';
import { absoluteUrl } from '../../../config/site';

const SITE_NAME = 'Evecta';

export type PageSeoProps = {
  title: string;
  description: string;
  path: string;
  /** Path under public/ or absolute image URL */
  image?: string;
  noindex?: boolean;
  type?: 'website' | 'article';
};

function resolveTitle(title: string): string {
  if (title.includes('Evecta') || title.includes(SITE_NAME)) {
    return title;
  }
  return `${title} | ${SITE_NAME}`;
}

export function PageSeo({
  title,
  description,
  path,
  image = '/Icon.png',
  noindex = false,
  type = 'website',
}: PageSeoProps) {
  const canonicalPath = path.startsWith('/') ? path : `/${path}`;
  const canonical = absoluteUrl(canonicalPath);
  const imageUrl = image.startsWith('http') ? image : absoluteUrl(image);
  const resolvedTitle = resolveTitle(title);

  return (
    <Helmet prioritizeSeoTags htmlAttributes={{ lang: 'en' }}>
      <title>{resolvedTitle}</title>
      <meta name="description" content={description} />
      <link rel="canonical" href={canonical} />
      <meta
        name="robots"
        content={noindex ? 'noindex, nofollow' : 'index, follow'}
      />

      <meta property="og:type" content={type} />
      <meta property="og:title" content={resolvedTitle} />
      <meta property="og:description" content={description} />
      <meta property="og:url" content={canonical} />
      <meta property="og:image" content={imageUrl} />
      <meta property="og:site_name" content={SITE_NAME} />

      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content={resolvedTitle} />
      <meta name="twitter:description" content={description} />
      <meta name="twitter:image" content={imageUrl} />
    </Helmet>
  );
}

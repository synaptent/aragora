import VerticalContent from './VerticalContent';

// Valid vertical slugs for static generation
const VERTICAL_SLUGS = ['legal', 'healthcare', 'finance', 'software', 'research'] as const;

// Generate static params for all verticals at build time
// Required for static export with dynamic routes
export function generateStaticParams() {
  return VERTICAL_SLUGS.map((slug) => ({ slug }));
}

interface PageProps {
  params: Promise<{ slug: string }>;
}

export default async function VerticalPage({ params }: PageProps) {
  const { slug } = await params;
  return <VerticalContent slug={slug} />;
}

import fs from 'node:fs';
import path from 'node:path';

describe('HomePage landing selection', () => {
  it('uses the canonical landing component for unauthenticated visitors', () => {
    const source = fs.readFileSync(path.join(process.cwd(), 'src/app/(app)/HomePage.tsx'), 'utf8');

    expect(source).toContain("from '@/components/landing/LandingPage'");
    expect(source).not.toContain("from '@/components/LandingPage'");
  });
});

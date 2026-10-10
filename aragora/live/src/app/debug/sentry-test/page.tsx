'use client';

import { useEffect, useState } from 'react';
import { notFound } from 'next/navigation';

function SentryTestTrigger() {
  const [boom, setBoom] = useState(false);

  useEffect(() => {
    if (
      process.env.NEXT_PUBLIC_SENTRY_DSN &&
      new URLSearchParams(window.location.search).get('boom') === '1'
    ) {
      setBoom(true);
    }
  }, []);

  if (boom) throw new Error('Aragora Live Sentry test error');

  return <p>Sentry test: add ?boom=1 with NEXT_PUBLIC_SENTRY_DSN configured.</p>;
}

export default function SentryTestPage() {
  if (process.env.NODE_ENV === 'production') notFound();

  return <SentryTestTrigger />;
}

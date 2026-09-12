'use client';

import { Suspense } from 'react';
import { CostDashboard } from '@/components/costs/CostDashboard';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';

function LoadingFallback() {
  return (
    <div className="animate-pulse space-y-4">
      <div className="h-8 bg-[var(--surface)] rounded w-1/3" />
      <div className="h-64 bg-[var(--surface)] rounded" />
      <div className="grid grid-cols-3 gap-4">
        <div className="h-32 bg-[var(--surface)] rounded" />
        <div className="h-32 bg-[var(--surface)] rounded" />
        <div className="h-32 bg-[var(--surface)] rounded" />
      </div>
    </div>
  );
}

export default function CostsPage() {
  return (
    <ProtectedRoute>
      <div className="container mx-auto px-4 py-6 max-w-6xl">
        <Suspense fallback={<LoadingFallback />}>
          <CostDashboard />
        </Suspense>
      </div>
    </ProtectedRoute>
  );
}

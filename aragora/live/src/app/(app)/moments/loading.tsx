'use client';

import { Skeleton, CardSkeleton, BadgeSkeleton, ParagraphSkeleton } from '@/components/Skeleton';

export default function MomentsLoading() {
  return (
    <div className="p-4 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <Skeleton width={160} height={24} label="Loading page title" />
          <Skeleton width={280} height={14} label="Loading page description" />
        </div>
        <div className="flex gap-2">
          <Skeleton width={100} height={36} rounded="md" />
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <BadgeSkeleton width={70} />
        <BadgeSkeleton width={90} />
        <BadgeSkeleton width={80} />
        <BadgeSkeleton width={60} />
        <BadgeSkeleton width={75} />
      </div>

      {/* Timeline View */}
      <div className="space-y-6">
        {/* Date Separator */}
        <div className="flex items-center gap-4">
          <Skeleton width={100} height={14} />
          <div className="flex-1 h-px bg-border" />
        </div>

        {/* Moment Cards */}
        <div className="grid grid-cols-2 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="p-4 bg-surface border border-border rounded-lg space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Skeleton width={24} height={24} rounded="sm" />
                  <Skeleton width={100} height={14} />
                </div>
                <Skeleton width={60} height={10} />
              </div>
              <ParagraphSkeleton lines={2} />
              <div className="flex items-center gap-3 pt-2">
                <BadgeSkeleton width={50} />
                <BadgeSkeleton width={60} />
              </div>
              <div className="flex justify-between items-center pt-2 border-t border-border">
                <Skeleton width={80} height={10} />
                <div className="flex gap-2">
                  <Skeleton width={28} height={28} rounded="md" />
                  <Skeleton width={28} height={28} rounded="md" />
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Another Date Separator */}
        <div className="flex items-center gap-4">
          <Skeleton width={100} height={14} />
          <div className="flex-1 h-px bg-border" />
        </div>

        {/* More Cards */}
        <div className="grid grid-cols-2 gap-4">
          {[1, 2].map((i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      </div>
    </div>
  );
}

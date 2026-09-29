'use client';

interface SectionHeaderProps {
  title: string;
}

export function SectionHeader({ title }: SectionHeaderProps) {
  return (
    <div className="text-center mb-8">
      <p className="text-[var(--accent)]/50 font-theme-data text-xs mb-2">{'═'.repeat(30)}</p>
      <h2 className="text-[var(--accent)] font-theme-data text-lg">
        {'>'} {title}
      </h2>
      <p className="text-[var(--accent)]/50 font-theme-data text-xs mt-2">{'═'.repeat(30)}</p>
    </div>
  );
}

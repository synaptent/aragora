'use client';

export function WelcomeStep() {
  return (
    <div className="space-y-6">
      <div className="text-center">
        <div className="text-6xl mb-4">
          <span role="img" aria-label="rocket">
            &#128640;
          </span>
        </div>
        <h3 className="text-xl font-theme-data text-[var(--accent)] mb-2">Welcome to Aragora</h3>
        <p className="text-sm text-text-muted">Multi-agent AI debates for better team decisions</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <FeatureCard
          icon="&#128161;"
          title="Stress-Test Ideas"
          description="Get diverse perspectives on any decision"
        />
        <FeatureCard
          icon="&#128200;"
          title="Track Consensus"
          description="See how AI agents agree or disagree"
        />
        <FeatureCard
          icon="&#128196;"
          title="Decision Receipts"
          description="Auditable records of every debate"
        />
      </div>

      <div className="text-center">
        <p className="text-sm text-text-muted">This wizard will help you:</p>
        <ul className="text-sm text-text mt-2 space-y-1">
          <li>1. Set up your workspace</li>
          <li>2. Invite your team</li>
          <li>3. Run your first debate</li>
          <li>4. View your decision receipt</li>
        </ul>
        <p className="text-xs text-text-muted mt-4">Takes about 10-15 minutes</p>
      </div>
    </div>
  );
}

interface FeatureCardProps {
  icon: string;
  title: string;
  description: string;
}

function FeatureCard({ icon, title, description }: FeatureCardProps) {
  return (
    <div className="p-4 border border-[var(--accent)]/20 rounded-lg text-center">
      <div className="text-2xl mb-2">{icon}</div>
      <div className="text-sm font-theme-data text-[var(--accent)]">{title}</div>
      <div className="text-xs text-text-muted mt-1">{description}</div>
    </div>
  );
}

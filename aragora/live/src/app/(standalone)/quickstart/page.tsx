import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Quickstart | ARAGORA',
  description:
    'Get from zero to a working adversarial AI debate in under a minute. Install, run, and share decisions.',
  openGraph: {
    title: 'Quickstart — ARAGORA',
    description:
      'Get from zero to a working adversarial AI debate in under a minute.',
    siteName: 'ARAGORA',
  },
};

function CodeBlock({
  children,
  lang,
}: {
  children: string;
  lang?: string;
}) {
  return (
    <div className="relative group">
      {lang && (
        <span className="absolute top-2 right-3 text-[10px] font-mono text-[var(--text-muted)] uppercase">
          {lang}
        </span>
      )}
      <pre className="p-4 bg-[var(--bg)] border border-[var(--border)] overflow-x-auto text-sm font-mono text-[var(--text)] leading-relaxed">
        <code>{children}</code>
      </pre>
    </div>
  );
}

function Step({
  number,
  title,
  children,
}: {
  number: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-12">
      <div className="flex items-center gap-3 mb-4">
        <span className="flex items-center justify-center w-8 h-8 text-sm font-mono font-bold bg-[var(--acid-green)]/20 text-[var(--acid-green)] border border-[var(--acid-green)]/30">
          {number}
        </span>
        <h2 className="text-lg font-mono font-bold text-[var(--text)]">
          {title}
        </h2>
      </div>
      <div className="ml-11 space-y-4">{children}</div>
    </section>
  );
}

export default function QuickstartPage() {
  return (
    <main className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      {/* Header */}
      <nav className="border-b border-[var(--border)] bg-[var(--surface)]/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link
            href="/"
            className="font-mono text-[var(--acid-green)] font-bold text-sm tracking-wider"
          >
            ARAGORA
          </Link>
          <div className="flex items-center gap-4">
            <Link
              href="/docs"
              className="text-xs font-mono text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
            >
              API DOCS
            </Link>
            <Link
              href="/try"
              className="text-xs font-mono text-[var(--acid-green)] hover:text-[var(--acid-green)]/80 transition-colors"
            >
              TRY IT
            </Link>
          </div>
        </div>
      </nav>

      <div className="max-w-3xl mx-auto px-4 py-12">
        {/* Title */}
        <h1 className="text-2xl md:text-3xl font-mono font-bold text-[var(--acid-green)] mb-2">
          Quickstart
        </h1>
        <p className="text-sm font-mono text-[var(--text-muted)] mb-12">
          Get from zero to a working adversarial debate in under a minute.
        </p>

        {/* Step 1 */}
        <Step number={1} title="Install">
          <CodeBlock lang="bash">pip install aragora-debate</CodeBlock>
        </Step>

        {/* Step 2 */}
        <Step number={2} title="Zero-Key Demo">
          <p className="text-sm font-mono text-[var(--text-muted)]">
            No API keys needed — runs with styled mock agents locally:
          </p>
          <CodeBlock lang="python">{`from aragora_debate.arena import Arena
from aragora_debate.styled_mock import StyledMockAgent
import asyncio

agents = [
    StyledMockAgent('analyst', style='supportive'),
    StyledMockAgent('critic', style='critical'),
    StyledMockAgent('pm', style='balanced'),
]
arena = Arena(question='Should we migrate to microservices?', agents=agents)
result = asyncio.run(arena.run())
print(result.receipt.to_markdown())`}</CodeBlock>
          <p className="text-sm font-mono text-[var(--text-muted)]">
            Three agents debate, critique each other, vote, and produce an
            audit-ready decision receipt.
          </p>
        </Step>

        {/* Step 3 */}
        <Step number={3} title="Add Real AI Models">
          <p className="text-sm font-mono text-[var(--text-muted)]">
            Set at least one API key:
          </p>
          <CodeBlock lang="bash">{`export ANTHROPIC_API_KEY="sk-ant-..."   # Claude
# or
export OPENAI_API_KEY="sk-..."          # GPT`}</CodeBlock>
          <p className="text-sm font-mono text-[var(--text-muted)]">
            Then run a real multi-model debate:
          </p>
          <CodeBlock lang="python">{`import asyncio
from aragora import Arena, Environment, DebateProtocol

env = Environment(task="Design a rate limiter for our API")
protocol = DebateProtocol(rounds=3, consensus="majority")

# Arena auto-discovers available agents from your API keys
arena = Arena(env, protocol=protocol)
result = asyncio.run(arena.run())
print(result.summary)`}</CodeBlock>
        </Step>

        {/* Step 4 */}
        <Step number={4} title="TypeScript SDK">
          <CodeBlock lang="bash">npm install @aragora/sdk</CodeBlock>
          <CodeBlock lang="typescript">{`import { AragoraClient } from "@aragora/sdk";

const client = new AragoraClient({ baseUrl: "http://localhost:8080" });
const result = await client.debates.create({
  task: "Should we use microservices or a monolith?",
  agents: ["claude", "openai"],
  rounds: 3,
});
console.log(result.summary);`}</CodeBlock>
        </Step>

        {/* Step 5 */}
        <Step number={5} title="Self-Host">
          <CodeBlock lang="bash">
            docker compose -f deploy/demo/docker-compose.yml up
          </CodeBlock>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm font-mono">
            <div className="p-3 border border-[var(--border)] bg-[var(--surface)]">
              <span className="text-[var(--acid-green)]">Landing page</span>
              <span className="text-[var(--text-muted)] ml-2">
                localhost:3000
              </span>
            </div>
            <div className="p-3 border border-[var(--border)] bg-[var(--surface)]">
              <span className="text-[var(--acid-green)]">API docs</span>
              <span className="text-[var(--text-muted)] ml-2">
                localhost:8080/api/v2/docs
              </span>
            </div>
            <div className="p-3 border border-[var(--border)] bg-[var(--surface)]">
              <span className="text-[var(--acid-green)]">Playground</span>
              <span className="text-[var(--text-muted)] ml-2">
                localhost:3000/playground
              </span>
            </div>
            <div className="p-3 border border-[var(--border)] bg-[var(--surface)]">
              <span className="text-[var(--acid-green)]">CLI</span>
              <span className="text-[var(--text-muted)] ml-2">
                aragora debate &quot;your question&quot;
              </span>
            </div>
          </div>
        </Step>

        {/* Next steps */}
        <div className="border-t border-[var(--border)] pt-8 mt-4">
          <h2 className="text-sm font-mono text-[var(--text-muted)] uppercase tracking-wider mb-4">
            Next Steps
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Link
              href="/try"
              className="p-4 border border-[var(--acid-green)]/30 bg-[var(--acid-green)]/5 hover:bg-[var(--acid-green)]/10 transition-colors"
            >
              <span className="text-sm font-mono font-bold text-[var(--acid-green)]">
                Try a debate now
              </span>
              <p className="text-xs font-mono text-[var(--text-muted)] mt-1">
                No install needed — run in your browser
              </p>
            </Link>
            <Link
              href="/docs"
              className="p-4 border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              <span className="text-sm font-mono font-bold text-[var(--text)]">
                API Reference
              </span>
              <p className="text-xs font-mono text-[var(--text-muted)] mt-1">
                Swagger + Redoc for all 3,000+ endpoints
              </p>
            </Link>
          </div>
        </div>

        {/* Footer */}
        <div className="text-center py-8 mt-8 border-t border-[var(--border)]">
          <Link
            href="/"
            className="text-xs font-mono text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
          >
            ARAGORA // DECISION INTEGRITY PLATFORM
          </Link>
        </div>
      </div>
    </main>
  );
}

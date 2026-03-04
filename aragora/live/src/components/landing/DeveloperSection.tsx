'use client';

import { useState } from 'react';
import { useTheme } from '@/context/ThemeContext';

const PYTHON_SNIPPET = `pip install aragora-debate

from aragora_debate import Debate, create_agent

debate = Debate(topic="Should we use Kubernetes?", rounds=2)
debate.add_agent(create_agent("anthropic", name="pro"))
debate.add_agent(create_agent("openai", name="con"))

result = await debate.run()
print(result.final_answer)  # Consensus with confidence score`;

const CURL_SNIPPET = `curl -X POST https://api.aragora.ai/api/v1/debates \\
  -H "Authorization: Bearer $ARAGORA_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "topic": "Should we use Kubernetes?",
    "agents": ["claude", "gpt4", "gemini"],
    "rounds": 2
  }'`;

const TYPESCRIPT_SNIPPET = `npm install @aragora/sdk

import { Aragora } from '@aragora/sdk';

const client = new Aragora({ apiKey: process.env.ARAGORA_API_KEY });

const result = await client.debates.create({
  topic: "Should we use Kubernetes?",
  agents: ["claude", "gpt4", "gemini"],
  rounds: 2,
});

console.log(result.verdict, result.confidence);`;

type Tab = 'python' | 'typescript' | 'curl';

const TABS: { id: Tab; label: string; code: string }[] = [
  { id: 'python', label: 'Python', code: PYTHON_SNIPPET },
  { id: 'typescript', label: 'TypeScript', code: TYPESCRIPT_SNIPPET },
  { id: 'curl', label: 'cURL', code: CURL_SNIPPET },
];

export function DeveloperSection() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const [activeTab, setActiveTab] = useState<Tab>('python');
  const [copied, setCopied] = useState(false);

  const activeCode = TABS.find((t) => t.id === activeTab)?.code || '';

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(activeCode);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = activeCode;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section
      className="px-4"
      style={{
        paddingTop: '120px',
        paddingBottom: '120px',
        borderTop: '1px solid var(--border)',
        fontFamily: 'var(--font-landing)',
      }}
    >
      <div className="max-w-3xl mx-auto">
        <p
          className="text-center uppercase tracking-widest"
          style={{
            fontSize: isDark ? '16px' : '18px',
            color: 'var(--text-muted)',
            marginBottom: '20px',
          }}
        >
          {isDark ? '> FOR DEVELOPERS' : 'FOR DEVELOPERS'}
        </p>
        <h2
          className="text-center"
          style={{
            fontSize: isDark ? '28px' : '32px',
            fontWeight: isDark ? 700 : 600,
            color: 'var(--text)',
            marginBottom: '12px',
          }}
        >
          5 lines to your first debate
        </h2>
        <p
          className="text-center max-w-xl mx-auto"
          style={{
            fontSize: '14px',
            color: 'var(--text-muted)',
            marginBottom: '48px',
          }}
        >
          No API keys needed for mock agents. Add real LLMs with one line.
        </p>

        {/* Code block */}
        <div
          style={{
            borderRadius: 'var(--radius-card, 8px)',
            border: '1px solid var(--border)',
            overflow: 'hidden',
            boxShadow: 'var(--shadow-card)',
          }}
        >
          {/* Tab bar */}
          <div
            className="flex items-center justify-between"
            style={{
              borderBottom: '1px solid var(--border)',
              backgroundColor: isDark ? 'rgba(0,0,0,0.3)' : 'var(--surface)',
            }}
          >
            <div className="flex">
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className="px-4 py-3 text-xs font-bold transition-colors cursor-pointer"
                  style={{
                    color: activeTab === tab.id ? 'var(--accent)' : 'var(--text-muted)',
                    borderBottom: activeTab === tab.id ? '2px solid var(--accent)' : '2px solid transparent',
                    backgroundColor: 'transparent',
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <button
              onClick={handleCopy}
              className="px-3 py-1 mr-2 text-xs transition-colors cursor-pointer"
              style={{
                color: copied ? 'var(--accent)' : 'var(--text-muted)',
                backgroundColor: 'transparent',
                border: 'none',
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
          {/* Code content */}
          <pre
            className="overflow-x-auto"
            style={{
              padding: '24px',
              margin: 0,
              fontSize: '13px',
              lineHeight: '1.7',
              color: isDark ? 'var(--acid-green, #39ff14)' : 'var(--text)',
              backgroundColor: isDark ? 'rgba(0,0,0,0.5)' : 'var(--surface)',
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            <code>{activeCode}</code>
          </pre>
        </div>

        {/* Links */}
        <div className="flex items-center justify-center gap-6 mt-8">
          <a
            href="/developer"
            className="text-sm font-semibold transition-all hover:scale-[1.02]"
            style={{
              border: '1px solid var(--accent)',
              borderRadius: 'var(--radius-button)',
              color: 'var(--accent)',
              backgroundColor: 'transparent',
              padding: '14px 32px',
            }}
          >
            API Docs
          </a>
          <a
            href="https://github.com/synaptent/aragora"
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm transition-colors"
            style={{ color: 'var(--text-muted)' }}
          >
            GitHub &rarr;
          </a>
        </div>
      </div>
    </section>
  );
}

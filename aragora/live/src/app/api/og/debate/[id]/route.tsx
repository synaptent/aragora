import { ImageResponse } from 'next/og';
import { NextRequest } from 'next/server';

export const runtime = 'edge';

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

// Agent neon colors matching the debate viewer palette
const AGENT_COLORS = ['#39ff14', '#00ffff', '#bf00ff', '#ffd700', '#ff0040'];

async function fetchDebate(debateId: string) {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/playground/debate/${debateId}`,
      { next: { revalidate: 300 } },
    );
    if (!res.ok) return null;
    const data = await res.json();
    return data?.data ?? data;
  } catch {
    return null;
  }
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const debate = await fetchDebate(id);

  // Fallback card when debate can't be fetched
  if (!debate) {
    return new ImageResponse(
      (
        <div
          style={{
            width: '100%',
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: '#0a0a0a',
            padding: '60px',
          }}
        >
          <div
            style={{
              fontSize: 28,
              fontFamily: 'monospace',
              color: '#39ff14',
              letterSpacing: '4px',
            }}
          >
            ARAGORA
          </div>
          <div
            style={{
              fontSize: 18,
              fontFamily: 'monospace',
              color: '#9a9a9a',
              marginTop: '16px',
            }}
          >
            Multi-Agent AI Debate
          </div>
        </div>
      ),
      { width: 1200, height: 630 },
    );
  }

  const confidencePercent = Math.round((debate.confidence ?? 0) * 100);
  const agentCount = debate.participants?.length ?? 0;
  const topic =
    debate.topic?.length > 90
      ? debate.topic.slice(0, 87) + '...'
      : debate.topic ?? 'Untitled Debate';
  const verdict =
    debate.verdict?.length > 160
      ? debate.verdict.slice(0, 157) + '...'
      : debate.verdict ?? '';
  const agents = (debate.participants ?? []).slice(0, 5);

  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: '#0a0a0a',
          padding: '48px 56px',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        {/* Subtle grid background */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundImage:
              'linear-gradient(rgba(57,255,20,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(57,255,20,0.03) 1px, transparent 1px)',
            backgroundSize: '40px 40px',
          }}
        />

        {/* Top accent line */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: '3px',
            background:
              'linear-gradient(90deg, #39ff14, #00ffff, #bf00ff, #ffd700, #ff0040)',
          }}
        />

        {/* Header row */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '32px',
          }}
        >
          <div
            style={{
              fontSize: 22,
              fontFamily: 'monospace',
              color: '#39ff14',
              letterSpacing: '6px',
              fontWeight: 700,
            }}
          >
            ARAGORA
          </div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '16px',
            }}
          >
            <div
              style={{
                fontSize: 14,
                fontFamily: 'monospace',
                color: '#9a9a9a',
                textTransform: 'uppercase',
              }}
            >
              {agentCount} AGENTS
            </div>
            {debate.consensus_reached && (
              <div
                style={{
                  fontSize: 14,
                  fontFamily: 'monospace',
                  color: '#39ff14',
                  textTransform: 'uppercase',
                }}
              >
                CONSENSUS
              </div>
            )}
          </div>
        </div>

        {/* Topic */}
        <div
          style={{
            fontSize: 38,
            fontFamily: 'monospace',
            fontWeight: 700,
            color: '#e0e0e0',
            lineHeight: 1.25,
            marginBottom: '24px',
            maxHeight: '120px',
            overflow: 'hidden',
          }}
        >
          {topic}
        </div>

        {/* Verdict + confidence bar */}
        {verdict && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
              marginBottom: '32px',
              padding: '20px',
              border: '1px solid rgba(57,255,20,0.25)',
              backgroundColor: 'rgba(57,255,20,0.03)',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div
                style={{
                  fontSize: 12,
                  fontFamily: 'monospace',
                  color: '#39ff14',
                  letterSpacing: '3px',
                  fontWeight: 700,
                }}
              >
                VERDICT
              </div>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}
              >
                <div
                  style={{
                    fontSize: 12,
                    fontFamily: 'monospace',
                    color: '#9a9a9a',
                  }}
                >
                  CONFIDENCE
                </div>
                {/* Confidence bar */}
                <div
                  style={{
                    width: '100px',
                    height: '8px',
                    backgroundColor: '#1a1a1a',
                    border: '1px solid rgba(57,255,20,0.2)',
                    display: 'flex',
                  }}
                >
                  <div
                    style={{
                      width: `${confidencePercent}%`,
                      height: '100%',
                      backgroundColor: '#39ff14',
                    }}
                  />
                </div>
                <div
                  style={{
                    fontSize: 14,
                    fontFamily: 'monospace',
                    color: '#39ff14',
                    fontWeight: 700,
                  }}
                >
                  {confidencePercent}%
                </div>
              </div>
            </div>
            <div
              style={{
                fontSize: 16,
                fontFamily: 'monospace',
                color: '#e0e0e0',
                lineHeight: 1.4,
              }}
            >
              {verdict}
            </div>
          </div>
        )}

        {/* Agent badges */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            marginTop: 'auto',
          }}
        >
          {agents.map((agent: string, i: number) => (
            <div
              key={agent}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 14px',
                border: `1px solid ${AGENT_COLORS[i % AGENT_COLORS.length]}40`,
                backgroundColor: `${AGENT_COLORS[i % AGENT_COLORS.length]}08`,
              }}
            >
              <div
                style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  backgroundColor: AGENT_COLORS[i % AGENT_COLORS.length],
                }}
              />
              <span
                style={{
                  fontSize: 13,
                  fontFamily: 'monospace',
                  color: AGENT_COLORS[i % AGENT_COLORS.length],
                  textTransform: 'uppercase',
                  fontWeight: 700,
                }}
              >
                {agent}
              </span>
            </div>
          ))}
        </div>
      </div>
    ),
    { width: 1200, height: 630 },
  );
}

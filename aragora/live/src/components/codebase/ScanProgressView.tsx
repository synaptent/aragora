'use client';

import { useState, useEffect } from 'react';

interface ScanProgressViewProps {
  scanType: 'quick' | 'full' | 'secrets';
}

interface ScanPhase {
  name: string;
  description: string;
  duration: number; // in seconds
}

const SCAN_PHASES: Record<string, ScanPhase[]> = {
  quick: [
    { name: 'Initializing', description: 'Setting up scan environment', duration: 2 },
    { name: 'Pattern Matching', description: 'Scanning for vulnerability patterns', duration: 8 },
    { name: 'Analysis', description: 'Analyzing findings', duration: 3 },
    { name: 'Report Generation', description: 'Generating security report', duration: 2 },
  ],
  full: [
    { name: 'Initializing', description: 'Setting up scan environment', duration: 3 },
    { name: 'Dependency Analysis', description: 'Scanning package dependencies', duration: 20 },
    { name: 'CVE Lookup', description: 'Checking CVE databases', duration: 15 },
    { name: 'Code Analysis', description: 'Deep code pattern analysis', duration: 30 },
    { name: 'Hotspot Detection', description: 'Identifying complexity hotspots', duration: 10 },
    { name: 'Report Generation', description: 'Generating comprehensive report', duration: 5 },
  ],
  secrets: [
    { name: 'Initializing', description: 'Setting up scan environment', duration: 2 },
    { name: 'File Scanning', description: 'Scanning current files for secrets', duration: 10 },
    { name: 'History Scanning', description: 'Scanning git history', duration: 15 },
    { name: 'Validation', description: 'Validating findings', duration: 5 },
    { name: 'Report Generation', description: 'Generating secrets report', duration: 3 },
  ],
};

export function ScanProgressView({ scanType }: ScanProgressViewProps) {
  const [currentPhase, setCurrentPhase] = useState(0);
  const [phaseProgress, setPhaseProgress] = useState(0);
  const [filesScanned, setFilesScanned] = useState(0);
  const [findingsCount, setFindingsCount] = useState(0);

  const phases = SCAN_PHASES[scanType];
  const totalPhases = phases.length;

  useEffect(() => {
    let cancelled = false;

    const runSimulation = async () => {
      for (let i = 0; i < phases.length; i++) {
        if (cancelled) return;

        setCurrentPhase(i);
        const phase = phases[i];
        const steps = 20;
        const stepDuration = (phase.duration * 1000) / steps;

        for (let step = 0; step <= steps; step++) {
          if (cancelled) return;
          await new Promise((resolve) => setTimeout(resolve, stepDuration));
          setPhaseProgress((step / steps) * 100);

          // Simulate files and findings
          if (i >= 1) {
            setFilesScanned((prev) => Math.min(prev + Math.floor(Math.random() * 5), 500));
            if (Math.random() > 0.8) {
              setFindingsCount((prev) => prev + 1);
            }
          }
        }
      }
    };

    runSimulation();

    return () => {
      cancelled = true;
    };
  }, [phases]);

  const overallProgress = ((currentPhase + phaseProgress / 100) / totalPhases) * 100;

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-theme-data text-[var(--acid-green)]">
            Scanning in Progress...
          </h3>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            {phases[currentPhase]?.description || 'Processing...'}
          </p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-theme-data text-[var(--acid-green)]">
            {Math.round(overallProgress)}%
          </div>
          <div className="text-xs text-[var(--text-muted)]">Complete</div>
        </div>
      </div>

      {/* Overall Progress Bar */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs text-[var(--text-muted)]">
          <span>Overall Progress</span>
          <span>
            Phase {currentPhase + 1} of {totalPhases}
          </span>
        </div>
        <div className="h-3 bg-[var(--bg)] rounded-full overflow-hidden">
          <div
            className="h-full bg-[var(--acid-green)] transition-all duration-300"
            style={{ width: `${overallProgress}%` }}
          />
        </div>
      </div>

      {/* Phase Progress */}
      <div className="space-y-3">
        {phases.map((phase, index) => {
          const isComplete = index < currentPhase;
          const isCurrent = index === currentPhase;
          const _isPending = index > currentPhase;

          return (
            <div
              key={phase.name}
              className={`flex items-center gap-3 p-3 rounded transition-colors ${
                isCurrent
                  ? 'bg-[var(--acid-green)]/10 border border-[var(--acid-green)]/30'
                  : isComplete
                    ? 'bg-green-500/5'
                    : 'bg-[var(--bg)]'
              }`}
            >
              <div
                className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-theme-data ${
                  isComplete
                    ? 'bg-green-500 text-white'
                    : isCurrent
                      ? 'bg-[var(--acid-green)] text-[var(--bg)] animate-pulse'
                      : 'bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)]'
                }`}
              >
                {isComplete ? '✓' : index + 1}
              </div>
              <div className="flex-1">
                <div
                  className={`text-sm font-theme-data ${
                    isCurrent
                      ? 'text-[var(--acid-green)]'
                      : isComplete
                        ? 'text-green-400'
                        : 'text-[var(--text-muted)]'
                  }`}
                >
                  {phase.name}
                </div>
                {isCurrent && (
                  <div className="mt-1 h-1 bg-[var(--bg)] rounded overflow-hidden">
                    <div
                      className="h-full bg-[var(--acid-green)] transition-all duration-300"
                      style={{ width: `${phaseProgress}%` }}
                    />
                  </div>
                )}
              </div>
              <div className="text-xs text-[var(--text-muted)]">
                {isComplete ? 'Done' : isCurrent ? `${Math.round(phaseProgress)}%` : 'Pending'}
              </div>
            </div>
          );
        })}
      </div>

      {/* Live Stats */}
      <div className="grid grid-cols-2 gap-4 pt-4 border-t border-[var(--border)]">
        <div className="text-center">
          <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">{filesScanned}</div>
          <div className="text-xs text-[var(--text-muted)]">Files Scanned</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-theme-data text-yellow-400">{findingsCount}</div>
          <div className="text-xs text-[var(--text-muted)]">Potential Findings</div>
        </div>
      </div>

      {/* Animated Scanner */}
      <div className="relative h-8 bg-[var(--bg)] rounded overflow-hidden">
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-xs font-theme-data text-[var(--text-muted)]">
            {scanType === 'quick'
              ? 'Pattern matching...'
              : scanType === 'full'
                ? 'Deep analysis...'
                : 'Scanning for secrets...'}
          </span>
        </div>
        <div
          className="absolute top-0 left-0 h-full w-1/4 bg-gradient-to-r from-transparent via-[var(--acid-green)]/20 to-transparent animate-pulse"
          style={{ animation: 'scan 2s linear infinite' }}
        />
      </div>

      <style jsx>{`
        @keyframes scan {
          0% {
            transform: translateX(-100%);
          }
          100% {
            transform: translateX(400%);
          }
        }
      `}</style>
    </div>
  );
}

export default ScanProgressView;

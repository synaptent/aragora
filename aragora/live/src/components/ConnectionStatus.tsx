'use client';

interface ConnectionStatusProps {
  connected: boolean;
}

export function ConnectionStatus({ connected }: ConnectionStatusProps) {
  return (
    <div className="flex items-center gap-2">
      <div
        className={`w-2 h-2 rounded-full ${connected ? 'bg-success animate-pulse' : 'bg-warning'}`}
      />
      <span className="text-sm text-text-muted">{connected ? 'Connected' : 'Disconnected'}</span>
    </div>
  );
}

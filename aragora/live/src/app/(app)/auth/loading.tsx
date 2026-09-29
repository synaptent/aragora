export default function AuthLoading() {
  return (
    <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] flex items-center justify-center">
      <div className="text-center">
        <div className="font-theme-data text-[var(--acid-green)] animate-pulse text-lg mb-2">
          AUTHENTICATING...
        </div>
        <div className="font-theme-data text-[var(--text-muted)] text-xs">Please wait</div>
      </div>
    </main>
  );
}

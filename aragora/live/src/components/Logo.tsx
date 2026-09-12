'use client';

interface LogoProps {
  size?: 'sm' | 'md' | 'lg';
  pixelSize?: number;
  onClick?: () => void;
  className?: string;
}

const sizes = { sm: 16, md: 24, lg: 32 };

export function Logo({ size = 'md', pixelSize, onClick, className = '' }: LogoProps) {
  const dimension = pixelSize ?? sizes[size];
  // Use dedicated logo-mark assets for in-app rendering; keep favicons for the browser tab.
  // Pick the closest asset and scale with pixelated rendering when needed.
  const assetSize = dimension <= 16 ? 16 : dimension <= 32 ? 32 : 64;
  const src = `/logo-mark-${assetSize}.png`;
  const image = (
    <img
      src={src}
      alt="Aragora"
      width={assetSize}
      height={assetSize}
      style={{ width: dimension, height: dimension, imageRendering: 'pixelated' }}
      className="block transition-all group-hover:drop-shadow-[0_0_10px_rgba(57,255,20,0.7)] group-hover:brightness-110"
    />
  );

  if (!onClick) {
    return <div className={`group flex-shrink-0 ${className}`}>{image}</div>;
  }

  return (
    <button
      onClick={onClick}
      className={`group flex-shrink-0 transition-all focus:outline-none focus:ring-2 focus:ring-acid-green/50 rounded ${className}`}
      aria-label="Aragora menu"
      type="button"
    >
      {image}
    </button>
  );
}

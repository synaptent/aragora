'use client';

import { getAgentColors } from '@/utils/agentColors';
import type { NodePosition } from './types';
import { getBranchColor, getNodeTypeIcon } from './utils';

function NodeTypeIcon({ type }: { type: string }) {
  return <span className="font-bold">{getNodeTypeIcon(type)}</span>;
}

export interface GraphNodeProps {
  position: NodePosition;
  isSelected: boolean;
  onClick: () => void;
}

export function GraphNode({ position, isSelected, onClick }: GraphNodeProps) {
  const { node, x, y } = position;
  const colors = getAgentColors(node.agent_id);
  const branchColor = getBranchColor(node.branch_id || 'main');

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onClick();
    }
  };

  return (
    <g
      transform={`translate(${x}, ${y})`}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-label={`${node.node_type} by ${node.agent_id}, ${(node.confidence * 100).toFixed(0)}% confidence`}
      className="cursor-pointer focus:outline-none"
    >
      {/* Node circle */}
      <circle
        r={isSelected ? 28 : 24}
        className={`${isSelected ? 'fill-acid-green/30' : 'fill-surface'} stroke-2 transition-all duration-200`}
        style={{
          stroke: isSelected ? '#00ff00' : colors.text.replace('text-', '#'),
          filter: isSelected ? 'drop-shadow(0 0 8px #00ff00)' : undefined,
        }}
      />

      {/* Node type icon */}
      <text
        textAnchor="middle"
        dominantBaseline="central"
        className={`text-xs font-theme-data ${branchColor}`}
        style={{ pointerEvents: 'none' }}
      >
        <NodeTypeIcon type={node.node_type} />
      </text>

      {/* Confidence indicator */}
      {node.confidence > 0 && (
        <text y={35} textAnchor="middle" className="text-[10px] font-theme-data fill-text-muted">
          {(node.confidence * 100).toFixed(0)}%
        </text>
      )}

      {/* Agent label */}
      <text y={-35} textAnchor="middle" className={`text-[10px] font-theme-data ${colors.text}`}>
        {node.agent_id.slice(0, 8)}
      </text>
    </g>
  );
}

export default GraphNode;

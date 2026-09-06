/** React Flow 커스텀 노드 (SPEC §2.5).
 *
 * "어디서 막혔는지"가 텍스트가 아니라 그림에서 즉시 읽혀야 한다.
 * 그래서 진행률은 채움 폭으로, at_risk 는 다른 무엇보다 먼저 보이게 그린다.
 */
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";

import type { NodeStatus } from "../api";

export interface ArchNodeData extends Record<string, unknown> {
  label: string;
  nodeKey: string;
  status: NodeStatus;
  progress: number;
  ticketCount: number;
  doneCount: number;
  delayedTickets: number;
  highlighted: boolean;
  dimmed: boolean;
}

export type ArchFlowNode = Node<ArchNodeData, "arch">;

export function ArchNode({ data }: NodeProps<ArchFlowNode>) {
  const classes = ["arch-node", data.status];
  if (data.highlighted) classes.push("highlighted");
  if (data.dimmed) classes.push("dimmed");

  return (
    <div className={classes.join(" ")} title={data.nodeKey}>
      <Handle type="target" position={Position.Top} />
      {/* at_risk 여도 진행률은 그대로 보여준다 — 얼마나 하다 막혔는지가 정보다 */}
      <span className="fill-clip">
        <i className="fill" style={{ width: `${Math.round(data.progress * 100)}%` }} />
      </span>
      {data.delayedTickets >= 2 && <div className="risk-badge">지연 {data.delayedTickets}</div>}
      <div className="content">
        <div className="label">{data.label}</div>
        <div className="meta">
          {data.doneCount}/{data.ticketCount} 티켓
          {data.ticketCount > 0 && ` · ${Math.round(data.progress * 100)}%`}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

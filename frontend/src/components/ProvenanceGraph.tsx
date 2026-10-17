import { useQuery } from "@tanstack/react-query";
import { Handle, type NodeProps, Position, ReactFlow, ReactFlowProvider, useReactFlow } from "@xyflow/react";
import { Bot, Database, FileText, Mail, ShieldCheck, Wallet } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useMemo } from "react";
import { api } from "../api";
import { graphFromEvents, graphFromTrace, type MgNode } from "../lib/graph";
import { cn } from "../lib/utils";
import { latestDecision, useLive, useRunEvents } from "../store";
import { Card, CardHeader } from "./ui/card";

const STATUS_STYLE = {
  good: "border-ok/70 bg-ok/10",
  bad: "border-bad bg-bad/15 shadow-[0_0_24px_-6px] shadow-bad/60",
  warn: "border-warn/80 bg-warn/12",
  neutral: "border-line bg-panel-2",
} as const;

function iconFor(n: MgNode["data"]) {
  if (n.kind === "tool_call") return Bot;
  if (n.kind === "proposal") return Wallet;
  if (n.kind === "decision") return ShieldCheck;
  if (n.label.startsWith("Email")) return Mail;
  if (n.label.startsWith("Invoice")) return FileText;
  return Database;
}

function GraphNode({ data }: NodeProps<MgNode>) {
  const Icon = iconFor(data);
  const decision = data.kind === "decision";
  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 260, damping: 24 }}
      className={cn("w-53 rounded-xl border px-3 py-2.5 transition-colors duration-500", STATUS_STYLE[data.status])}
    >
      <Handle type="target" position={Position.Left} />
      <div className="flex items-start gap-2">
        <Icon className={cn("mt-0.5 size-4 shrink-0", data.status === "bad" ? "text-bad" : data.status === "good" ? "text-ok" : data.status === "warn" ? "text-warn" : "text-muted")} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className={cn("truncate font-semibold leading-tight", decision ? "font-display text-[17px] tracking-wide" : "text-[13px]",
            decision && data.status === "bad" && "text-bad", decision && data.status === "good" && "text-ok", decision && data.status === "warn" && "text-warn",
            data.kind === "tool_call" && "font-mono text-[12.5px]")}>
            {data.label}
          </div>
          {data.detail && <div className="mt-0.5 truncate font-mono text-[11px] text-muted">{data.detail}</div>}
        </div>
        {data.trust && (
          <span className={cn("text-[9px] font-bold uppercase tracking-widest", data.trust === "trusted" ? "text-ok" : "text-warn")}>
            {data.trust}
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Right} />
    </motion.div>
  );
}

function HeadingNode({ data }: NodeProps<MgNode>) {
  return <div className="w-53 text-[12px] font-bold uppercase tracking-[0.16em] text-faint">{data.label}</div>;
}

const nodeTypes = { mg: GraphNode, head: HeadingNode };

function Refit({ count }: { count: number }) {
  const flow = useReactFlow();
  useEffect(() => {
    const id = window.setTimeout(() => void flow.fitView({ padding: 0.08, duration: 450, maxZoom: 1.25 }), 60);
    return () => window.clearTimeout(id);
  }, [count, flow]);
  return null;
}

function Flow() {
  const events = useRunEvents();
  const decision = latestDecision(events);
  const trace = useQuery({ queryKey: ["trace", decision?.decisionId], queryFn: () => api.trace(decision!.decisionId), enabled: !!decision });
  const graph = useMemo(() => (trace.data ? graphFromTrace(trace.data) : graphFromEvents(events)), [trace.data, events]);

  return (
    <div className="relative min-h-110 flex-1">
      <ReactFlow
        nodes={graph.nodes}
        edges={graph.edges}
        nodeTypes={nodeTypes}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        zoomOnDoubleClick={false}
        panOnScroll={false}
        proOptions={{ hideAttribution: true }}
        minZoom={0.4}
      >
        <Refit count={graph.nodes.length} />
      </ReactFlow>
      {graph.nodes.length === 0 && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center px-8 text-center text-muted">
          Run a scenario. The graph builds itself as the agent works, and every value stays tied to the source it came from.
        </div>
      )}
    </div>
  );
}

export function ProvenanceGraph() {
  const run = useLive((s) => s.run);
  return (
    <Card className="flex flex-col p-0">
      <div className="px-4 pt-4">
        <CardHeader
          title="Where every value came from"
          aside={
            <div className="flex flex-wrap gap-3 text-xs text-muted">
              <span className="inline-flex items-center gap-1.5"><i className="h-0.75 w-4 rounded bg-ok" />Trusted source</span>
              <span className="inline-flex items-center gap-1.5"><i className="h-0.75 w-4 rounded bg-faint" />Untrusted, harmless</span>
              <span className="inline-flex items-center gap-1.5"><i className="h-1 w-4 rounded bg-bad" />Offending path</span>
            </div>
          }
        />
      </div>
      <ReactFlowProvider key={run?.session_id ?? "idle"}>
        <Flow />
      </ReactFlowProvider>
    </Card>
  );
}

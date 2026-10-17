import { useQuery } from "@tanstack/react-query";
import { Background, BackgroundVariant, Handle, type NodeProps, Position, ReactFlow, ReactFlowProvider, useReactFlow } from "@xyflow/react";
import { Bot, Database, FileText, Loader2, Mail, ShieldCheck, Wallet } from "lucide-react";
import { motion } from "motion/react";
import { memo, useEffect, useMemo } from "react";
import { api } from "../api";
import { useVerdict } from "../hooks/useVerdict";
import { graphFromEvents, graphFromTrace, type MgNode } from "../lib/graph";
import { cn } from "../lib/utils";
import { runPhase, useLive, useRunEvents } from "../store";
import { Card, CardHeader } from "./ui/card";

const STATUS_STYLE = {
  good: "border-ok/50 bg-[#f1f8f3]",
  bad: "border-bad border-2 bg-[#fcf0ee]",
  warn: "border-warn/60 bg-[#fdf5e8]",
  neutral: "border-line bg-white",
} as const;

const ICON_TONE = { good: "text-ok", bad: "text-bad", warn: "text-warn", neutral: "text-faint" } as const;

function iconFor(n: MgNode["data"]) {
  if (n.pending) return Loader2;
  if (n.kind === "tool_call") return Bot;
  if (n.kind === "proposal") return Wallet;
  if (n.kind === "decision") return ShieldCheck;
  if (n.label.startsWith("Email")) return Mail;
  if (n.label.startsWith("Invoice")) return FileText;
  return Database;
}

const GraphNode = memo(function GraphNode({ data }: NodeProps<MgNode>) {
  const Icon = iconFor(data);
  const decision = data.kind === "decision" && !data.pending;
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: "easeOut" }}
      className={cn(
        "w-53 rounded-xl border px-3 py-2.5 shadow-[0_1px_2px_rgba(31,29,24,0.05)] transition-colors duration-500",
        data.pending ? "animate-breathe border-dashed border-faint/60 bg-panel" : STATUS_STYLE[data.status],
      )}
    >
      <Handle type="target" position={Position.Left} />
      <div className="flex items-start gap-2">
        <Icon className={cn("mt-0.5 size-4 shrink-0", data.pending ? "animate-spin text-seal" : ICON_TONE[data.status])} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className={cn("truncate font-semibold leading-tight", decision ? "font-display text-[18px] font-bold tracking-wide" : "text-[13px]",
            decision && ICON_TONE[data.status], decision && data.status === "neutral" && "text-ink",
            data.kind === "tool_call" && !data.pending && "font-mono text-[12.5px]", data.pending && "text-muted")}>
            {data.label}
          </div>
          {data.detail && <div className="mt-0.5 truncate font-mono text-[11px] text-muted">{data.detail}</div>}
        </div>
        {data.trust && (
          <span className={cn("rounded px-1 text-[9.5px] font-bold uppercase tracking-wider", data.trust === "trusted" ? "bg-ok/10 text-ok" : "bg-warn/10 text-warn")}>
            {data.trust}
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Right} />
    </motion.div>
  );
});

function HeadingNode({ data }: NodeProps<MgNode>) {
  return <div className="w-53 font-display text-[15px] font-semibold italic text-muted">{data.label}</div>;
}

const nodeTypes = { mg: GraphNode, head: HeadingNode };

function Refit({ count }: { count: number }) {
  const flow = useReactFlow();
  useEffect(() => {
    const id = window.setTimeout(() => void flow.fitView({ padding: 0.1, duration: 320, maxZoom: 1.2 }), 40);
    return () => window.clearTimeout(id);
  }, [count, flow]);
  return null;
}

function Flow() {
  const events = useRunEvents();
  const run = useLive((s) => s.run);
  const starting = useLive((s) => s.starting);
  const { latest: decision, ready } = useVerdict();
  const working = runPhase(starting, run, events).active && !decision;
  const trace = useQuery({ queryKey: ["trace", decision?.decisionId], queryFn: () => api.trace(decision!.decisionId), enabled: !!decision });
  const graph = useMemo(() => {
    if (trace.data && ready) return graphFromTrace(trace.data);
    if (decision && !ready) return graphFromEvents(events.filter((e) => e.type !== "decision"), true); // gate still checking
    return graphFromEvents(events, working || !!starting);
  }, [trace.data, ready, decision, events, working, starting]);

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
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.3} color="#d9d2c3" />
        <Refit count={graph.nodes.length} />
      </ReactFlow>
      {graph.nodes.length === 0 && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center px-10 text-center">
          <p className="max-w-md font-display text-[19px] italic leading-relaxed text-muted">
            Run a scenario. The graph builds itself as the agent works, and every value stays tied to the source it came from.
          </p>
        </div>
      )}
    </div>
  );
}

export function ProvenanceGraph() {
  const run = useLive((s) => s.run);
  return (
    <Card className="flex flex-col p-0">
      <div className="px-5 pt-4">
        <CardHeader
          title="Where every value came from"
          aside={
            <div className="flex flex-wrap gap-3.5 text-[12.5px] text-muted">
              <span className="inline-flex items-center gap-1.5"><i className="h-0.75 w-4 rounded bg-ok" />Trusted source</span>
              <span className="inline-flex items-center gap-1.5"><i className="h-0.75 w-4 rounded bg-[#a39c8c]" />Untrusted, harmless</span>
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

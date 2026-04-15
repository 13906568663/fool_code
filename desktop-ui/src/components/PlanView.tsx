import { useState, useMemo, useCallback } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  ListChecks,
  LoaderCircle,
  PenLine,
  Play,
  Trash2,
} from "lucide-react";
import { MarkdownContent } from "./MessageBubble";
import type { Artifact, TodoItem } from "../types";
import { fetchPlanContent } from "../services/api";

/* ------------------------------------------------------------------ */
/*  Markdown parser                                                    */
/* ------------------------------------------------------------------ */

interface RawStep {
  title: string;
  content: string;
}

interface ParsedPlan {
  title: string;
  intro: string;
  steps: RawStep[];
}

function parsePlanContent(markdown: string): ParsedPlan {
  if (!markdown.trim()) return { title: "", intro: "", steps: [] };

  let title = "";
  let body = markdown;

  const h1Match = body.match(/^#\s+(.+)\n?/);
  if (h1Match) {
    title = h1Match[1].trim();
    body = body.slice(h1Match[0].length).trim();
  }

  if (/^##\s+/m.test(body)) {
    const parts = body.split(/^(?=##\s)/m);
    const intro = parts[0].replace(/^#\s+.+\n?/, "").trim();
    const steps: RawStep[] = [];
    for (let i = 1; i < parts.length; i++) {
      const sec = parts[i];
      const nl = sec.indexOf("\n");
      const heading =
        nl === -1
          ? sec.replace(/^##\s+/, "").trim()
          : sec.slice(0, nl).replace(/^##\s+/, "").trim();
      const stepBody = nl === -1 ? "" : sec.slice(nl + 1).trim();
      steps.push({ title: heading, content: stepBody });
    }
    return { title, intro, steps };
  }

  if (/^###\s+/m.test(body)) {
    const parts = body.split(/^(?=###\s)/m);
    const intro = parts[0].trim();
    const steps: RawStep[] = [];
    for (let i = 1; i < parts.length; i++) {
      const sec = parts[i];
      const nl = sec.indexOf("\n");
      const heading =
        nl === -1
          ? sec.replace(/^###\s+/, "").trim()
          : sec.slice(0, nl).replace(/^###\s+/, "").trim();
      const stepBody = nl === -1 ? "" : sec.slice(nl + 1).trim();
      steps.push({ title: heading, content: stepBody });
    }
    if (steps.length > 0) return { title, intro, steps };
  }

  if (/^\d+\.\s+/m.test(body)) {
    const parts = body.split(/^(?=\d+\.\s)/m);
    const intro = parts[0].trim();
    const steps: RawStep[] = [];
    for (let i = 1; i < parts.length; i++) {
      const sec = parts[i];
      const nl = sec.indexOf("\n");
      const raw =
        nl === -1
          ? sec.replace(/^\d+\.\s+/, "").trim()
          : sec.slice(0, nl).replace(/^\d+\.\s+/, "").trim();
      const titleStr = raw.replace(/^\*\*(.+?)\*\*:?\s*/, "$1") || raw;
      const stepBody = nl === -1 ? "" : sec.slice(nl + 1).trim();
      steps.push({ title: titleStr, content: stepBody });
    }
    if (steps.length > 0) return { title, intro, steps };
  }

  const bulletLines = body.split(/\n/).filter((l) => /^[-*]\s+/.test(l));
  if (bulletLines.length >= 2) {
    const steps: RawStep[] = bulletLines.map((line) => ({
      title: line.replace(/^[-*]\s+/, "").replace(/^\*\*(.+?)\*\*:?\s*/, "$1").trim(),
      content: "",
    }));
    return { title, intro: "", steps };
  }

  return { title, intro: body, steps: [] };
}

/* ------------------------------------------------------------------ */
/*  Todo matching                                                      */
/* ------------------------------------------------------------------ */

function matchTodoToStep(
  step: RawStep,
  todos: TodoItem[],
  stepIdx: number,
): TodoItem | undefined {
  if (todos[stepIdx]) return todos[stepIdx];
  const titleLower = step.title.toLowerCase();
  return todos.find(
    (t) =>
      t.content &&
      (t.content.toLowerCase().includes(titleLower) ||
        titleLower.includes(t.content.toLowerCase())),
  );
}

/* ------------------------------------------------------------------ */
/*  Step row                                                           */
/* ------------------------------------------------------------------ */

interface StepItemProps {
  step: RawStep;
  index: number;
  isStreaming?: boolean;
  status?: "pending" | "in_progress" | "completed";
  isLast?: boolean;
}

function StepItem({ step, index, isStreaming, status, isLast }: StepItemProps) {
  const [expanded, setExpanded] = useState(false);
  const hasContent = Boolean(step.content?.trim());
  const autoExpand = isStreaming && isLast;
  const showContent = autoExpand || expanded;

  const statusIndicator = (() => {
    if (isStreaming && isLast)
      return <LoaderCircle size={14} className="animate-spin text-blue-500" />;
    if (status === "completed")
      return (
        <span className="flex h-[18px] w-[18px] items-center justify-center rounded-full bg-emerald-500 text-white">
          <Check size={10} strokeWidth={3} />
        </span>
      );
    if (status === "in_progress")
      return <LoaderCircle size={14} className="animate-spin text-blue-500" />;
    return (
      <span className="flex h-[18px] w-[18px] items-center justify-center rounded-full border border-slate-200 bg-white text-[10px] font-semibold text-slate-400">
        {index + 1}
      </span>
    );
  })();

  return (
    <div className="group/step">
      <button
        type="button"
        onClick={() => hasContent && setExpanded((v) => !v)}
        className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${
          hasContent ? "cursor-pointer hover:bg-slate-50" : "cursor-default"
        } ${!isLast ? "" : ""}`}
      >
        <span className="shrink-0">{statusIndicator}</span>
        <span
          className={`min-w-0 flex-1 text-[13px] leading-5 ${
            status === "completed"
              ? "text-slate-400 line-through"
              : status === "in_progress"
                ? "font-medium text-slate-800"
                : "text-slate-600"
          }`}
        >
          {step.title || "..."}
        </span>
        {hasContent && !autoExpand && (
          <span className="shrink-0 text-slate-300 opacity-0 transition group-hover/step:opacity-100">
            {showContent ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </span>
        )}
      </button>

      {showContent && hasContent && (
        <div className="mb-1 ml-[30px] mr-2 rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2.5 text-[13px] text-slate-600">
          <MarkdownContent content={step.content} />
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main PlanView                                                      */
/* ------------------------------------------------------------------ */

interface PlanViewProps {
  content: string;
  streaming?: boolean;
  todos?: TodoItem[];
  planStatus?: string;
  planReady?: boolean;
  planSlug?: string | null;
  onExecutePlan?: () => void;
  onDiscardPlan?: () => void;
  onRefinePlan?: () => void;
  onOpenArtifact?: (artifact: Artifact) => void;
}

export default function PlanView({
  content,
  streaming = false,
  todos = [],
  planStatus,
  planReady = false,
  planSlug,
  onExecutePlan,
  onDiscardPlan,
  onRefinePlan,
  onOpenArtifact,
}: PlanViewProps) {
  const parsed = useMemo(() => parsePlanContent(content), [content]);
  const [fetchingDetail, setFetchingDetail] = useState(false);

  const handleViewDetail = useCallback(async () => {
    if (!onOpenArtifact) return;

    if (planSlug) {
      setFetchingDetail(true);
      try {
        const result = await fetchPlanContent(planSlug);
        onOpenArtifact({
          fileName: `${planSlug}.md`,
          contentType: "document",
          content: result.content,
        });
      } catch {
        onOpenArtifact({
          fileName: "plan.md",
          contentType: "document",
          content,
        });
      } finally {
        setFetchingDetail(false);
      }
    } else {
      onOpenArtifact({
        fileName: "plan.md",
        contentType: "document",
        content,
      });
    }
  }, [content, planSlug, onOpenArtifact]);

  if (parsed.steps.length === 0) {
    return (
      <div>
        {streaming && !content && (
          <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500">
            <LoaderCircle size={14} className="animate-spin text-blue-500" />
            正在分析并制定计划...
          </div>
        )}
        {content && <MarkdownContent content={content} />}
      </div>
    );
  }

  const completedCount = todos.filter((t) => t.status === "completed").length;
  const isAllDone =
    planStatus === "completed" ||
    (todos.length > 0 && completedCount === parsed.steps.length);
  const showActions = planReady && !streaming;
  const isExecuting = todos.length > 0 && !isAllDone;
  const pct =
    parsed.steps.length > 0
      ? Math.round((completedCount / parsed.steps.length) * 100)
      : 0;

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <div className="flex items-center gap-2">
          <ListChecks size={15} className={isAllDone ? "text-emerald-500" : "text-slate-400"} />
          <span className="text-[13px] font-semibold text-slate-700">
            {parsed.title || "Plan"}
          </span>
          <span className="text-[11px] text-slate-400">
            {isAllDone
              ? "Done"
              : isExecuting
                ? `${completedCount}/${parsed.steps.length}`
                : `${parsed.steps.length} steps`}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          {streaming && (
            <LoaderCircle size={13} className="animate-spin text-blue-400" />
          )}
          {onOpenArtifact && !streaming && (
            <button
              type="button"
              onClick={() => void handleViewDetail()}
              disabled={fetchingDetail}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-slate-400 transition hover:bg-slate-50 hover:text-slate-600 disabled:opacity-50"
            >
              {fetchingDetail ? <LoaderCircle size={11} className="animate-spin" /> : <ExternalLink size={11} />}
              详情
            </button>
          )}
        </div>
      </div>

      {/* Progress bar during execution */}
      {isExecuting && (
        <div className="px-4">
          <div className="h-[3px] w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-blue-500 transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}

      {/* Intro */}
      {parsed.intro && (
        <div className="px-4 pb-1 pt-2 text-[13px] leading-6 text-slate-500">
          <MarkdownContent content={parsed.intro} />
        </div>
      )}

      {/* Steps */}
      <div className="px-1.5 py-1">
        {parsed.steps.map((step, idx) => {
          const todo = matchTodoToStep(step, todos, idx);
          const inferredStatus =
            todo?.status ??
            (planStatus === "completed" ? "completed" : undefined);
          return (
            <StepItem
              key={idx}
              step={step}
              index={idx}
              isStreaming={streaming && idx === parsed.steps.length - 1}
              status={inferredStatus}
              isLast={idx === parsed.steps.length - 1}
            />
          );
        })}
      </div>

      {/* Action bar -- Cursor style, below the steps */}
      {showActions && (
        <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-4 py-3">
          <button
            type="button"
            onClick={() => void handleViewDetail()}
            disabled={fetchingDetail}
            className="text-[12px] text-slate-400 transition hover:text-slate-600 disabled:opacity-50"
          >
            {fetchingDetail ? "加载中..." : "查看完整计划"}
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onDiscardPlan}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-500 transition hover:bg-slate-50"
            >
              <Trash2 size={12} />
              放弃
            </button>
            <button
              type="button"
              onClick={onRefinePlan}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-500 transition hover:bg-slate-50"
            >
              <PenLine size={12} />
              修改
            </button>
            <button
              type="button"
              onClick={onExecutePlan}
              className="inline-flex items-center gap-1 rounded-lg border border-transparent bg-blue-600 px-4 py-1.5 text-[12px] font-semibold text-white transition hover:bg-blue-700"
            >
              <Play size={12} />
              执行计划
            </button>
          </div>
        </div>
      )}

      {/* All done banner */}
      {isAllDone && (
        <div className="flex items-center gap-2 border-t border-emerald-100 bg-emerald-50/50 px-4 py-2.5">
          <Check size={14} className="text-emerald-500" />
          <span className="text-[12px] font-medium text-emerald-700">
            计划执行完成
          </span>
        </div>
      )}
    </div>
  );
}

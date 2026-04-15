import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Ban,
  ChevronDown,
  ChevronRight,
  FileSearch,
  Globe,
  Shield,
  ShieldCheck,
  TerminalSquare,
  Wrench,
} from "lucide-react";

interface PermissionDialogProps {
  toolName: string;
  input: string;
  onDecision: (decision: string) => void | Promise<void>;
}

type ToolIntent = {
  badge: string;
  tone: string;
  description: string;
  summaryLabel: string;
  summaryValue: string;
  icon: typeof TerminalSquare;
};

function parseInput(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function toPrettyInput(raw: string, parsed: unknown): string {
  if (parsed == null) return raw;
  try {
    return JSON.stringify(parsed, null, 2);
  } catch {
    return raw;
  }
}

function pickString(
  parsed: unknown,
  keys: string[],
): string {
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return "";
  const record = parsed as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

function summarizeRawInput(raw: string): string {
  const firstLine = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean);
  if (!firstLine) return "无附加参数";
  return firstLine.length > 140 ? `${firstLine.slice(0, 137)}...` : firstLine;
}

function getToolIntent(toolName: string, rawInput: string, parsed: unknown): ToolIntent {
  const command = pickString(parsed, ["command"]);
  const path = pickString(parsed, ["path", "file_path", "notebook_path"]);
  const query = pickString(parsed, ["pattern", "query", "url"]);
  const summaryFallback = summarizeRawInput(rawInput);

  switch (toolName) {
    case "bash":
    case "PowerShell":
      return {
        badge: "系统访问",
        tone: "bg-amber-50 text-amber-800 border-amber-200",
        description: "该工具可以在当前工作区中执行终端命令。",
        summaryLabel: "命令",
        summaryValue: command || summaryFallback,
        icon: TerminalSquare,
      };
    case "write_file":
    case "edit_file":
    case "NotebookEdit":
      return {
        badge: "文件修改",
        tone: "bg-rose-50 text-rose-800 border-rose-200",
        description: "此操作可能会修改磁盘上的文件。",
        summaryLabel: "目标",
        summaryValue: path || summaryFallback,
        icon: Wrench,
      };
    case "read_file":
    case "glob_search":
    case "grep_search":
    case "Skill":
      return {
        badge: "读取项目数据",
        tone: "bg-sky-50 text-sky-800 border-sky-200",
        description: "该工具会读取文件或搜索当前项目内容。",
        summaryLabel: path || query ? "范围" : "请求",
        summaryValue: path || query || summaryFallback,
        icon: FileSearch,
      };
    case "WebFetch":
    case "WebSearch":
      return {
        badge: "网络访问",
        tone: "bg-emerald-50 text-emerald-800 border-emerald-200",
        description: "此操作需要访问外部网络。",
        summaryLabel: "目标",
        summaryValue: query || summaryFallback,
        icon: Globe,
      };
    default:
      return {
        badge: "工具请求",
        tone: "bg-violet-50 text-violet-800 border-violet-200",
        description: "默认权限模式在运行此工具前需要你的确认。",
        summaryLabel: "请求",
        summaryValue: summaryFallback,
        icon: Wrench,
      };
  }
}

export default function PermissionDialog({
  toolName,
  input,
  onDecision,
}: PermissionDialogProps) {
  const [expanded, setExpanded] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const parsedInput = useMemo(() => parseInput(input), [input]);
  const prettyInput = useMemo(
    () => toPrettyInput(input, parsedInput),
    [input, parsedInput]
  );
  const intent = useMemo(
    () => getToolIntent(toolName, input, parsedInput),
    [toolName, input, parsedInput]
  );

  const handleDecision = useCallback(
    async (decision: string) => {
      if (submitting) return;
      setSubmitting(true);
      setError("");
      try {
        await onDecision(decision);
      } catch (err) {
        setError(err instanceof Error ? err.message : "提交决策失败");
        setSubmitting(false);
      }
    },
    [onDecision, submitting]
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (submitting) return;
      if (event.key === "Escape") {
        event.preventDefault();
        void handleDecision("deny");
        return;
      }
      if (event.key === "Enter" && event.shiftKey) {
        event.preventDefault();
        void handleDecision("always");
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        void handleDecision("allow");
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleDecision, submitting]);

  const IntentIcon = intent.icon;

  return (
    <>
      <div className="fixed inset-0 z-[200] bg-slate-950/35 backdrop-blur-sm" />
      <div className="fixed inset-0 z-[201] flex items-center justify-center p-4">
        <div className="w-full max-w-[680px] overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-[0_28px_80px_rgba(15,23,42,0.22)]">
          <div className="border-b border-slate-200 bg-[linear-gradient(135deg,#fff7ed_0%,#ffffff_55%,#f8fafc_100%)] px-6 py-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-800">
                  <AlertTriangle size={14} />
                  需要授权
                </div>
                <h3 className="text-xl font-semibold tracking-tight text-slate-900">
                  运行前请确认
                </h3>
                <p className="mt-1 text-sm leading-6 text-slate-600">
                  默认权限模式已暂停执行，请确认 Fool Code 即将执行的操作。
                </p>
              </div>
              <div
                className={`shrink-0 rounded-full border px-3 py-1 text-xs font-semibold ${intent.tone}`}
              >
                {intent.badge}
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-[1.35fr_0.85fr]">
              <div className="rounded-2xl border border-slate-200 bg-white/85 p-4">
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                  <IntentIcon size={14} />
                  {intent.summaryLabel}
                </div>
                <div className="text-sm font-medium leading-6 text-slate-900 break-all">
                  {intent.summaryValue}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                  <Wrench size={14} />
                  工具
                </div>
                <div className="mb-1 text-base font-semibold text-violet-700">
                  {toolName}
                </div>
                <div className="text-sm leading-6 text-slate-600">
                  {intent.description}
                </div>
              </div>
            </div>
          </div>

          <div className="space-y-4 px-6 py-5">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <button
                type="button"
                onClick={() => setExpanded((prev) => !prev)}
                className="flex w-full items-center gap-2 bg-transparent text-left text-sm font-semibold text-slate-700"
              >
                {expanded ? (
                  <ChevronDown size={16} className="text-slate-400" />
                ) : (
                  <ChevronRight size={16} className="text-slate-400" />
                )}
                原始工具输入
                <span className="ml-auto text-xs font-normal text-slate-400">
                  {expanded ? "收起详情" : "查看详情"}
                </span>
              </button>

              {expanded && (
                <pre className="mt-3 max-h-[260px] overflow-y-auto rounded-2xl border border-slate-200 bg-slate-950 p-4 font-mono text-xs leading-6 text-slate-100 whitespace-pre-wrap break-all">
                  {prettyInput}
                </pre>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-500">
              <span className="inline-flex items-center gap-1.5">
                <Shield size={14} />
                `Enter` 允许一次
              </span>
              <span className="inline-flex items-center gap-1.5">
                <ShieldCheck size={14} />
                `Shift + Enter` 始终允许
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Ban size={14} />
                `Esc` 拒绝
              </span>
            </div>

            {error && (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {error}
              </div>
            )}
          </div>

          <div className="flex flex-col gap-3 border-t border-slate-200 bg-slate-50 px-6 py-5 md:flex-row md:items-center md:justify-between">
            <div className="text-sm leading-6 text-slate-500">
              请选择最小必要权限，确保工作流顺畅运行。
            </div>

            <div className="flex flex-col gap-2 sm:flex-row">
              <button
                type="button"
                onClick={() => void handleDecision("deny")}
                disabled={submitting}
                className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition-colors hover:border-slate-400 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                拒绝
              </button>
              <button
                type="button"
                onClick={() => void handleDecision("allow")}
                disabled={submitting}
                className="rounded-xl border border-blue-200 bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                允许一次
              </button>
              <button
                type="button"
                onClick={() => void handleDecision("always")}
                disabled={submitting}
                className="rounded-xl border border-emerald-200 bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                始终允许
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

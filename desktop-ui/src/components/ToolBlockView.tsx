import { useMemo, useState, useEffect, useCallback } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  ExternalLink,
  LoaderCircle,
  TriangleAlert,
  Terminal,
  Pencil,
  Eye,
  FolderSearch,
  Globe,
  Puzzle,
  Bot,
  Shield,
} from "lucide-react";
import type { Artifact, ToolBlock } from "../types";
import DiffView, { type DiffHunk } from "./DiffView";

export type ToolCategory =
  | "terminal"
  | "file-read"
  | "file-write"
  | "search"
  | "browser"
  | "mcp"
  | "subagent"
  | "hook"
  | "default";

interface CategoryTheme {
  icon: React.ReactNode;
  accent: string;
  iconBg: string;
  iconFg: string;
}

export function categorize(name: string): ToolCategory {
  const n = name.toLowerCase();
  if (n.startsWith("hook:")) return "hook";
  if (n.startsWith("子代理:") || n.startsWith("subagent")) return "subagent";
  if (/bash|shell|exec|run_command|terminal|execute|command/.test(n)) return "terminal";
  if (/read_file|cat|head|tail|view|read/.test(n)) return "file-read";
  if (/write|edit|create|save|append|patch|str_replace|replace/.test(n)) return "file-write";
  if (/search|grep|find|glob|rg|ripgrep|semantic/.test(n)) return "search";
  if (/browser|navigate|screenshot|click|scroll|url|web|fetch/.test(n)) return "browser";
  if (/mcp/.test(n)) return "mcp";
  return "default";
}

function theme(cat: ToolCategory): CategoryTheme {
  const s = 14;
  switch (cat) {
    case "terminal":
      return { icon: <Terminal size={s} />, accent: "#10B981", iconBg: "bg-emerald-50", iconFg: "text-emerald-600" };
    case "file-read":
      return { icon: <Eye size={s} />, accent: "#3B82F6", iconBg: "bg-blue-50", iconFg: "text-blue-500" };
    case "file-write":
      return { icon: <Pencil size={s} />, accent: "#F59E0B", iconBg: "bg-amber-50", iconFg: "text-amber-600" };
    case "search":
      return { icon: <FolderSearch size={s} />, accent: "#8B5CF6", iconBg: "bg-violet-50", iconFg: "text-violet-500" };
    case "browser":
      return { icon: <Globe size={s} />, accent: "#F97316", iconBg: "bg-orange-50", iconFg: "text-orange-500" };
    case "mcp":
      return { icon: <Puzzle size={s} />, accent: "#6366F1", iconBg: "bg-indigo-50", iconFg: "text-indigo-500" };
    case "subagent":
      return { icon: <Bot size={s} />, accent: "#06B6D4", iconBg: "bg-cyan-50", iconFg: "text-cyan-600" };
    case "hook":
      return { icon: <Shield size={s} />, accent: "#64748B", iconBg: "bg-slate-100", iconFg: "text-slate-500" };
    default:
      return { icon: <Puzzle size={s} />, accent: "#4C84FF", iconBg: "bg-blue-50", iconFg: "text-[#3767D6]" };
  }
}

export function cleanName(name: string): string {
  if (name.startsWith("hook:")) return name.slice(5);
  if (name.startsWith("子代理: ")) return name.slice(5);
  if (name.startsWith("mcp__")) {
    const rest = name.slice(5);
    const sep = rest.indexOf("__");
    if (sep > 0) {
      const server = rest.slice(0, sep);
      const tool = rest.slice(sep + 2);
      return `${server} · ${tool}`;
    }
    return rest;
  }
  return name;
}

function tryParseField(raw: string | undefined, ...keys: string[]): string {
  if (!raw) return "";
  try {
    const obj = JSON.parse(raw);
    for (const k of keys) if (typeof obj[k] === "string" && obj[k]) return obj[k];
  } catch {
    /* not JSON */
  }
  return "";
}

function inputSummary(cat: ToolCategory, input?: string): string {
  if (!input) return "";
  switch (cat) {
    case "terminal":
      return tryParseField(input, "command", "cmd") || input.slice(0, 200);
    case "file-read":
    case "file-write":
      return tryParseField(input, "path", "file_path", "filename", "file") || input.slice(0, 200);
    case "search":
      return tryParseField(input, "query", "pattern", "search", "regex") || input.slice(0, 200);
    case "browser":
      return tryParseField(input, "url", "href", "address") || input.slice(0, 200);
    case "mcp":
      return tryParseField(input, "description", "command", "query", "url", "path", "name") || (input.length <= 200 ? input : "");
    default:
      return tryParseField(input, "command", "path", "query", "url", "name") || (input.length <= 200 ? input : "");
  }
}

function isTerminalLike(cat: ToolCategory) {
  return cat === "terminal";
}

interface ParsedWriteOutput {
  type?: string;
  filePath?: string;
  structuredPatch?: DiffHunk[];
}

interface ParsedTerminalOutput {
  stdout: string;
  stderr: string;
  interrupted: boolean;
  returnCodeInterpretation?: string;
  durationMs?: number;
  noOutputExpected?: boolean;
  exitCode?: number;
}

function tryParseTerminalOutput(
  cat: ToolCategory,
  output: string | undefined,
): ParsedTerminalOutput | null {
  if (cat !== "terminal" || !output) return null;
  try {
    const obj = JSON.parse(output);
    if (typeof obj.stdout !== "string" && typeof obj.stderr !== "string")
      return null;
    const rci = obj.returnCodeInterpretation as string | undefined;
    let exitCode: number | undefined;
    if (rci && rci.startsWith("exit_code:")) {
      exitCode = parseInt(rci.split(":")[1], 10);
      if (Number.isNaN(exitCode)) exitCode = undefined;
    }
    return {
      stdout: obj.stdout ?? "",
      stderr: obj.stderr ?? "",
      interrupted: !!obj.interrupted,
      returnCodeInterpretation: rci,
      durationMs: typeof obj.durationMs === "number" ? obj.durationMs : undefined,
      noOutputExpected: !!obj.noOutputExpected,
      exitCode,
    };
  } catch {
    return null;
  }
}

function tryParseDiffOutput(
  cat: ToolCategory,
  output: string | undefined,
): ParsedWriteOutput | null {
  if (cat !== "file-write" || !output) return null;
  try {
    const obj = JSON.parse(output);
    if (
      Array.isArray(obj.structuredPatch) &&
      obj.structuredPatch.length > 0 &&
      obj.structuredPatch[0].lines
    ) {
      return {
        type: obj.type,
        filePath: obj.filePath,
        structuredPatch: obj.structuredPatch,
      };
    }
  } catch {
    /* not JSON or no patch */
  }
  return null;
}

function friendlyErrorText(output: string): string {
  const timeoutMatch = output.match(/(?:MCP error -32603|timed?\s*out).*?(\d+)\s*ms/i);
  if (timeoutMatch) {
    const seconds = Math.round(parseInt(timeoutMatch[1]) / 1000);
    return `命令执行超时 (${seconds}秒)`;
  }
  if (/MCP error -32600/i.test(output)) return "请求格式无效";
  if (/MCP error -32601/i.test(output)) return "工具或方法不存在";
  if (/MCP error -32602/i.test(output)) return "参数格式错误";
  if (/MCP error -32603/i.test(output)) return output.replace(/MCP error -32603:\s*/i, "").trim();
  if (/connection refused|ECONNREFUSED/i.test(output)) return "连接被拒绝，目标服务可能未启动";
  if (/connection reset|ECONNRESET/i.test(output)) return "连接被中断";
  if (/ETIMEDOUT/i.test(output)) return "连接超时";
  if (/EHOSTUNREACH/i.test(output)) return "主机不可达";
  if (/ENOTFOUND/i.test(output)) return "域名解析失败";
  return output;
}

export default function ToolBlockView({
  block,
  onOpenArtifact,
}: {
  block: ToolBlock;
  onOpenArtifact?: (artifact: Artifact) => void;
}) {
  const cat = useMemo(() => categorize(block.name), [block.name]);
  const t = useMemo(() => theme(cat), [cat]);
  const summary = useMemo(() => inputSummary(cat, block.input), [cat, block.input]);
  const dark = useMemo(() => isTerminalLike(cat), [cat]);
  const displayOutput = useMemo(
    () => (block.output && block.error) ? friendlyErrorText(block.output) : block.output,
    [block.output, block.error],
  );

  const diffData = useMemo(
    () => tryParseDiffOutput(cat, block.output),
    [cat, block.output],
  );

  const termData = useMemo(
    () => tryParseTerminalOutput(cat, block.output),
    [cat, block.output],
  );

  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (block.status === "error") setExpanded(true);
  }, [block.status]);

  const copyOutput = useCallback(async () => {
    if (!block.output) return;
    try {
      await navigator.clipboard.writeText(block.output);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch { /* */ }
  }, [block.output]);

  const statusNode = useMemo(() => {
    if (block.status === "running")
      return (
        <span className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-400">
          <LoaderCircle size={11} className="animate-spin" />
          <span>运行中</span>
        </span>
      );
    if (block.status === "error")
      return (
        <span className="inline-flex items-center gap-1 text-[11px] font-medium text-rose-500">
          <TriangleAlert size={11} />
          <span>失败</span>
        </span>
      );
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-500">
        <CheckCircle2 size={11} />
        <span>完成</span>
      </span>
    );
  }, [block.status]);

  return (
    <div
      className="tool-block group/tool relative overflow-hidden rounded-xl transition-all"
      style={{
        borderLeft: `3px solid ${block.status === "error" ? "#EF4444" : t.accent}`,
        background: block.status === "error" ? "#FFF5F5" : "#FCFDFF",
      }}
    >
      {block.status === "running" && (
        <div className="tool-shimmer-bar" style={{ "--shimmer-color": t.accent } as React.CSSProperties} />
      )}

      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-white/80"
      >
        <span className={`inline-flex size-6 flex-shrink-0 items-center justify-center rounded-md ${t.iconBg} ${t.iconFg}`}>
          {t.icon}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="truncate text-[13px] font-semibold text-slate-700">
              {cleanName(block.name)}
            </span>
            {statusNode}
          </div>
          {summary && (
            <p className="mt-0.5 truncate font-mono text-[11px] leading-4 text-slate-400">
              {dark && <span className="mr-1 text-emerald-500/70">$</span>}
              {summary}
            </p>
          )}
        </div>

        <span className="flex-shrink-0 text-slate-300 transition-colors group-hover/tool:text-slate-400">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
      </button>

      {expanded && (
        <div className="tool-detail animate-tool-expand border-t border-[#EEF2F7]/60">
          {block.input && !(cat === "file-write" && diffData) && (
            <div className="px-3 pt-2.5 pb-1.5">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400/80">
                输入
              </div>
              {dark && summary ? (
                <div className="rounded-lg bg-[#0F172A] px-3 py-2">
                  <code className="block whitespace-pre-wrap break-all font-mono text-[11px] leading-5 text-emerald-300">
                    <span className="mr-1.5 select-none text-slate-500">$</span>
                    {summary}
                  </code>
                </div>
              ) : (
                <pre className="max-h-36 overflow-auto rounded-lg border border-slate-100 bg-slate-50/80 px-2.5 py-2 font-mono text-[11px] leading-5 text-slate-600">
                  {block.input}
                </pre>
              )}
            </div>
          )}

          {displayOutput && (
            <div className="px-3 pt-1.5 pb-2.5">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400/80">
                  {block.status === "running" ? "实时输出" : "输出"}
                </span>
                {block.status !== "running" && displayOutput.length > 20 && (
                  <div className="flex items-center gap-1">
                    {onOpenArtifact && (cat === "file-read" || cat === "file-write") && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          const fileName = tryParseField(block.input, "path", "file_path", "filename", "file") || block.name;
                          onOpenArtifact({
                            fileName,
                            contentType: "document",
                            content: block.output || "",
                          });
                        }}
                        className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                      >
                        <ExternalLink size={10} />
                        面板查看
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); void copyOutput(); }}
                      className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                    >
                      {copied ? <Check size={10} /> : <Copy size={10} />}
                      {copied ? "已复制" : "复制"}
                    </button>
                  </div>
                )}
              </div>
              {diffData && diffData.structuredPatch ? (
                <DiffView
                  hunks={diffData.structuredPatch}
                  filePath={diffData.filePath}
                  type={diffData.type as "create" | "update"}
                />
              ) : termData ? (
                <div className="overflow-hidden rounded-lg bg-[#0F172A]">
                  {/* stdout */}
                  {termData.stdout.trim() ? (
                    <pre className="max-h-48 overflow-auto px-3 py-2.5 font-mono text-[11px] leading-5 text-slate-300">
                      {termData.stdout}
                      {block.status === "running" && (
                        <span className="cursor-blink ml-px inline-block h-3 w-[5px] translate-y-[1px] bg-emerald-400" />
                      )}
                    </pre>
                  ) : termData.noOutputExpected && !termData.stderr.trim() ? (
                    <div className="px-3 py-2.5 text-[11px] text-slate-500 italic">
                      命令已执行，无输出
                    </div>
                  ) : !termData.stderr.trim() ? (
                    <div className="px-3 py-2.5 text-[11px] text-slate-500 italic">
                      (无 stdout 输出)
                    </div>
                  ) : null}
                  {/* stderr */}
                  {termData.stderr.trim() && (
                    <pre className={`max-h-32 overflow-auto border-t border-slate-700/50 px-3 py-2 font-mono text-[11px] leading-5 ${
                      termData.interrupted || termData.exitCode
                        ? "bg-[#1A0A0A] text-rose-300"
                        : "text-amber-300/80"
                    }`}>
                      {termData.stderr}
                    </pre>
                  )}
                  {/* status bar */}
                  {(termData.returnCodeInterpretation || termData.durationMs != null) && (
                    <div className="flex items-center gap-2 border-t border-slate-700/50 px-3 py-1.5">
                      {termData.returnCodeInterpretation === "timeout" && (
                        <span className="rounded bg-amber-900/40 px-1.5 py-0.5 text-[10px] font-medium text-amber-300">
                          超时
                        </span>
                      )}
                      {termData.exitCode != null && termData.exitCode !== 0 && (
                        <span className="rounded bg-rose-900/40 px-1.5 py-0.5 text-[10px] font-medium text-rose-300">
                          退出码 {termData.exitCode}
                        </span>
                      )}
                      {termData.exitCode === 0 && (
                        <span className="rounded bg-emerald-900/40 px-1.5 py-0.5 text-[10px] font-medium text-emerald-300">
                          成功
                        </span>
                      )}
                      {termData.durationMs != null && (
                        <span className="ml-auto text-[10px] text-slate-500">
                          {termData.durationMs >= 1000
                            ? `${(termData.durationMs / 1000).toFixed(1)}s`
                            : `${termData.durationMs}ms`}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              ) : dark ? (
                <pre
                  className={`tool-output-terminal max-h-48 overflow-auto rounded-lg px-3 py-2.5 font-mono text-[11px] leading-5 ${
                    block.error
                      ? "bg-[#1A0A0A] text-rose-300"
                      : "bg-[#0F172A] text-slate-300"
                  }`}
                >
                  {displayOutput}
                  {block.status === "running" && (
                    <span className="cursor-blink ml-px inline-block h-3 w-[5px] translate-y-[1px] bg-emerald-400" />
                  )}
                </pre>
              ) : (
                <pre
                  className={`max-h-48 overflow-auto rounded-lg border px-2.5 py-2 font-mono text-[11px] leading-5 ${
                    block.error
                      ? "border-rose-200 bg-rose-50/80 text-rose-600"
                      : "border-slate-100 bg-slate-50/80 text-slate-600"
                  }`}
                >
                  {displayOutput}
                </pre>
              )}
            </div>
          )}

          {block.status === "running" && !block.output && (
            <div className="px-3 pb-2.5 pt-1">
              <div className="h-1 overflow-hidden rounded-full bg-slate-100">
                <div className="tool-progress-bar h-full rounded-full" style={{ background: t.accent }} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

import {
  Children,
  isValidElement,
  memo,
  useCallback,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Brain,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  LoaderCircle,
  ImageIcon,
  FileText,
  FileSpreadsheet,
  Table2,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import type { Artifact, DisplayMessage, ToolBlock } from "../types";
import ToolBlockView, { cleanName } from "./ToolBlockView";
import PlanView from "./PlanView";
import { fetchFileContent, getFileCacheUrl } from "../services/api";

/* ------------------------------------------------------------------ */
/*  User message image-ref parsing                                    */
/* ------------------------------------------------------------------ */

const FILE_REF_RE =
  /(?:^|\n)?@((?:[A-Za-z]:[\\/]|\/)[^\s]+\.(?:jpg|jpeg|png|gif|webp|bmp|docx?|xlsx?|csv|tsv|txt|md|log|json|xml|ya?ml|toml|pdf))/gi;

const IMAGE_PLACEHOLDER_RE = /\[Image #[a-z0-9-]+\]/gi;
const DOC_PLACEHOLDER_RE = /\[Document: [^\]]+\]/gi;

function stripFileRefs(content: string): string {
  return content
    .replace(FILE_REF_RE, "")
    .replace(IMAGE_PLACEHOLDER_RE, "")
    .replace(DOC_PLACEHOLDER_RE, "")
    .trim();
}

function formatSize(bytes: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function FileCard({
  filename,
  category,
  size,
  onClick,
}: {
  filename: string;
  category: string;
  size: number;
  onClick?: () => void;
}) {
  const isSpreadsheet = category === "spreadsheet";
  const Icon = isSpreadsheet ? FileSpreadsheet : FileText;

  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex cursor-pointer items-center gap-2 rounded-2xl border px-3 py-2 transition hover:shadow-md ${
        isSpreadsheet
          ? "border-emerald-200 bg-emerald-50/60 hover:border-emerald-300"
          : "border-blue-200 bg-blue-50/60 hover:border-blue-300"
      }`}
    >
      <div
        className={`flex h-8 w-8 items-center justify-center rounded-lg ${
          isSpreadsheet
            ? "bg-emerald-100 text-emerald-600"
            : "bg-blue-100 text-blue-500"
        }`}
      >
        <Icon size={16} />
      </div>
      <div className="min-w-0 text-left">
        <p className="truncate text-[13px] font-medium text-slate-700 max-w-[200px]">
          {filename}
        </p>
        {size > 0 && (
          <p className="text-[11px] text-slate-400">{formatSize(size)}</p>
        )}
      </div>
    </button>
  );
}

function ImageThumbnail({
  url,
  alt,
  onOpenArtifact,
}: {
  url: string;
  alt?: string;
  onOpenArtifact?: (artifact: Artifact) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [failed, setFailed] = useState(false);

  const handleClick = useCallback(() => {
    if (onOpenArtifact) {
      onOpenArtifact({
        fileName: alt || "image",
        contentType: "image",
        content: url,
      });
    } else {
      setExpanded(true);
    }
  }, [url, alt, onOpenArtifact]);

  if (failed) {
    return (
      <div className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white/60 px-3 py-1.5 text-xs text-slate-400">
        <ImageIcon size={14} />
        <span className="max-w-[200px] truncate">{alt || "image"}</span>
      </div>
    );
  }

  return (
    <>
      <img
        src={url}
        alt={alt || ""}
        onClick={handleClick}
        onError={() => setFailed(true)}
        className="max-h-[180px] max-w-full cursor-pointer rounded-2xl border border-white/80 object-cover shadow-[0_4px_16px_rgba(0,0,0,0.08)] transition-transform hover:scale-[1.02]"
        loading="lazy"
      />
      {expanded && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setExpanded(false)}
        >
          <img
            src={url}
            alt={alt || ""}
            className="max-h-[90vh] max-w-[90vw] rounded-2xl shadow-2xl"
          />
        </div>
      )}
    </>
  );
}

function UserMessageContent({
  content,
  images,
  files,
  onOpenArtifact,
}: {
  content: string;
  images?: { url: string; alt: string }[];
  files?: {
    filename: string;
    category: string;
    size: number;
    fileId: string;
    markdownPath?: string;
    cachedPath?: string;
  }[];
  onOpenArtifact?: (artifact: Artifact) => void;
}) {
  const hasImages = images && images.length > 0;
  const hasFiles = files && files.length > 0;
  const textOnly = stripFileRefs(content);

  const handleFileClick = useCallback(
    async (f: {
      filename: string;
      category: string;
      size: number;
      markdownPath?: string;
      cachedPath?: string;
    }) => {
      if (!onOpenArtifact) return;

      onOpenArtifact({
        fileName: f.filename,
        contentType: "document",
        content: "正在加载文件内容…",
      });

      try {
        let textContent = "";
        let fileDataUrl: string | undefined;

        const mdPath = f.markdownPath;
        const binPath =
          f.cachedPath ||
          (mdPath && mdPath.endsWith(".md") ? mdPath.slice(0, -3) : "");

        if (mdPath) {
          const result = await fetchFileContent(mdPath);
          textContent = result.content;
        }

        if (binPath) {
          const ext = f.filename.split(".").pop()?.toLowerCase() ?? "";
          if (["xlsx", "xls", "docx", "doc", "pdf"].includes(ext)) {
            try {
              const url = getFileCacheUrl(binPath);
              const resp = await fetch(url);
              if (resp.ok) {
                const blob = await resp.blob();
                const buf = await blob.arrayBuffer();
                const bytes = new Uint8Array(buf);
                let binary = "";
                const chunkSize = 8192;
                for (let i = 0; i < bytes.length; i += chunkSize) {
                  binary += String.fromCharCode(
                    ...bytes.subarray(i, i + chunkSize),
                  );
                }
                const b64 = btoa(binary);
                const mimeMap: Record<string, string> = {
                  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                  xls: "application/vnd.ms-excel",
                  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                  doc: "application/msword",
                  pdf: "application/pdf",
                };
                fileDataUrl = `data:${mimeMap[ext] || blob.type};base64,${b64}`;
              }
            } catch {
              /* binary preview unavailable, text fallback */
            }
          }
        }

        onOpenArtifact({
          fileName: f.filename,
          contentType: "document",
          content: textContent || `文件: ${f.filename}\n类别: ${f.category}\n大小: ${formatSize(f.size)}`,
          fileDataUrl,
        });
      } catch {
        onOpenArtifact({
          fileName: f.filename,
          contentType: "document",
          content: `无法加载文件内容\n\n文件: ${f.filename}\n类别: ${f.category}\n大小: ${formatSize(f.size)}`,
        });
      }
    },
    [onOpenArtifact],
  );

  return (
    <div className="space-y-2.5">
      {hasImages && (
        <div className="flex flex-wrap gap-2">
          {images.map((img, i) => (
            <ImageThumbnail
              key={i}
              url={img.url}
              alt={img.alt}
              onOpenArtifact={onOpenArtifact}
            />
          ))}
        </div>
      )}
      {hasFiles && (
        <div className="flex flex-wrap gap-2">
          {files.map((f, i) => (
            <FileCard
              key={i}
              filename={f.filename}
              category={f.category}
              size={f.size}
              onClick={
                onOpenArtifact ? () => void handleFileClick(f) : undefined
              }
            />
          ))}
        </div>
      )}
      {textOnly && (
        <p className="whitespace-pre-wrap">{textOnly}</p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Utilities                                                         */
/* ------------------------------------------------------------------ */

function extractTextContent(node: ReactNode): string {
  return Children.toArray(node)
    .map((child) => {
      if (typeof child === "string" || typeof child === "number")
        return String(child);
      if (isValidElement<{ children?: ReactNode }>(child))
        return extractTextContent(child.props.children);
      return "";
    })
    .join("");
}

/**
 * Find the last safe split point (`\n\n` outside a code fence) so we can
 * memoise the stable prefix during streaming.
 */
function findLastStableBreak(text: string): number {
  let inFence = false;
  let lastBreak = 0;
  for (let i = 0; i < text.length - 1; i++) {
    if (
      text[i] === "`" &&
      i + 2 < text.length &&
      text[i + 1] === "`" &&
      text[i + 2] === "`"
    ) {
      inFence = !inFence;
      i += 2;
      continue;
    }
    if (!inFence && text[i] === "\n" && text[i + 1] === "\n") {
      lastBreak = i + 2;
    }
  }
  return lastBreak;
}

/* ------------------------------------------------------------------ */
/*  Code Block — Syntax Highlighted                                   */
/* ------------------------------------------------------------------ */

function CodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable */
    }
  }, [code]);

  return (
    <div className="relative my-4 min-w-0">
      <div className="flex items-center justify-between rounded-t-[20px] border border-b-0 border-[#E7ECF3] bg-[#F0F4FA] px-4 py-2">
        <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
          {language || "code"}
        </span>
        <button
          type="button"
          onClick={() => void handleCopy()}
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium text-slate-500 transition hover:bg-white/80 hover:text-[#3767D6]"
          title="复制代码"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      <div className="overflow-x-auto rounded-b-[20px] border border-[#E7ECF3] bg-[#F8FAFF] shadow-[inset_0_1px_0_rgba(255,255,255,0.8)]">
        <SyntaxHighlighter
          language={language || "text"}
          style={oneLight}
          customStyle={{
            margin: 0,
            padding: "1rem",
            background: "transparent",
            fontSize: "13px",
            lineHeight: "1.5rem",
          }}
        >
          {code}
        </SyntaxHighlighter>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Table utils — parse DOM table, export to xlsx, toolbar             */
/* ------------------------------------------------------------------ */

function parseTableFromDOM(table: HTMLTableElement): string[][] {
  const rows: string[][] = [];
  table.querySelectorAll("tr").forEach((tr) => {
    const cells: string[] = [];
    tr.querySelectorAll("th, td").forEach((cell) => {
      cells.push(cell.textContent?.trim() ?? "");
    });
    if (cells.length > 0) rows.push(cells);
  });
  return rows;
}

async function tableDataToXlsxBlob(rows: string[][]): Promise<Blob> {
  const XLSX = await import("xlsx");
  const ws = XLSX.utils.aoa_to_sheet(rows);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
  const buf = XLSX.write(wb, { bookType: "xlsx", type: "array" });
  return new Blob([buf], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

function TableWithToolbar({
  children,
  className,
  onOpenArtifact,
  ...props
}: React.TableHTMLAttributes<HTMLTableElement> & {
  onOpenArtifact?: (artifact: Artifact) => void;
}) {
  const tableRef = useRef<HTMLTableElement>(null);

  const exportToArtifact = useCallback(async () => {
    if (!tableRef.current || !onOpenArtifact) return;
    const rows = parseTableFromDOM(tableRef.current);
    if (rows.length === 0) return;
    const blob = await tableDataToXlsxBlob(rows);
    const buf = await blob.arrayBuffer();
    const b64 = btoa(
      new Uint8Array(buf).reduce((s, b) => s + String.fromCharCode(b), ""),
    );
    const dataUrl = `data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,${b64}`;
    onOpenArtifact({
      fileName: "table.xlsx",
      contentType: "document",
      content: rows.map((r) => r.join("\t")).join("\n"),
      fileDataUrl: dataUrl,
    });
  }, [onOpenArtifact]);

  return (
    <div className="group/table relative my-4">
      {onOpenArtifact && (
        <div className="pointer-events-none absolute -top-1 right-0 z-10 flex items-center gap-1 rounded-lg border border-[#E7ECF3] bg-white px-1 py-0.5 opacity-0 shadow-sm transition-opacity duration-150 group-hover/table:pointer-events-auto group-hover/table:opacity-100">
          <button
            type="button"
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-slate-500 transition hover:bg-[#F3F6FB] hover:text-slate-700"
            onClick={() => void exportToArtifact()}
          >
            <Table2 className="h-3 w-3" />
            在面板中查看
          </button>
        </div>
      )}
      <div className="overflow-x-auto rounded-[22px] border border-[#E7ECF3] bg-white shadow-[0_12px_28px_rgba(31,42,68,0.04)]">
        <table
          ref={tableRef}
          {...props}
          className={[
            "min-w-full border-collapse text-left text-sm",
            className,
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {children}
        </table>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Markdown renderer (stable components reference)                   */
/* ------------------------------------------------------------------ */

const remarkPlugins = [remarkGfm];

function buildMarkdownComponents(
  onOpenArtifact?: (artifact: Artifact) => void,
): Components {
  return {
  a: ({ className, children, ...props }) => (
    <a
      {...props}
      className={[
        "text-[#4C84FF] underline decoration-[#4C84FF]/30 underline-offset-2 transition-colors hover:text-[#3F76EE]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
    </a>
  ),
  p: ({ className, children, ...props }) => (
    <p
      {...props}
      className={[
        "my-2 whitespace-pre-wrap break-words text-[15px] leading-7 text-slate-700",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </p>
  ),
  h1: ({ className, children, ...props }) => (
    <h1
      {...props}
      className={[
        "mb-3 mt-6 text-[24px] font-semibold tracking-tight text-slate-800",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </h1>
  ),
  h2: ({ className, children, ...props }) => (
    <h2
      {...props}
      className={[
        "mb-3 mt-6 text-[20px] font-semibold tracking-tight text-slate-800",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </h2>
  ),
  h3: ({ className, children, ...props }) => (
    <h3
      {...props}
      className={[
        "mb-2 mt-5 text-[17px] font-semibold text-slate-800",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </h3>
  ),
  ul: ({ className, children, ...props }) => (
    <ul
      {...props}
      className={[
        "my-3 list-disc space-y-1.5 pl-5 text-slate-700",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </ul>
  ),
  ol: ({ className, children, ...props }) => (
    <ol
      {...props}
      className={[
        "my-3 list-decimal space-y-1.5 pl-5 text-slate-700",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </ol>
  ),
  li: ({ className, children, ...props }) => (
    <li
      {...props}
      className={[
        "pl-1 text-[15px] leading-7 text-slate-700",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </li>
  ),
  blockquote: ({ className, children, ...props }) => (
    <blockquote
      {...props}
      className={[
        "my-4 rounded-r-2xl border-l-[3px] border-[#4C84FF] bg-[#F8FAFF] px-4 py-3 text-slate-600",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </blockquote>
  ),
  hr: ({ className, ...props }) => (
    <hr
      {...props}
      className={[
        "my-6 border-0 border-t border-[#E7ECF3]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    />
  ),
  strong: ({ className, children, ...props }) => (
    <strong
      {...props}
      className={["font-semibold text-slate-800", className]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </strong>
  ),
  table: ({ className, children, ...props }) => (
    <TableWithToolbar
      {...props}
      className={className}
      onOpenArtifact={onOpenArtifact}
    >
      {children}
    </TableWithToolbar>
  ),
  thead: ({ className, children, ...props }) => (
    <thead
      {...props}
      className={["bg-[#F8FAFF]", className].filter(Boolean).join(" ")}
    >
      {children}
    </thead>
  ),
  th: ({ className, children, ...props }) => (
    <th
      {...props}
      className={[
        "border-b border-[#E7ECF3] px-4 py-3 text-[12px] font-semibold uppercase tracking-[0.04em] text-slate-500",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </th>
  ),
  tr: ({ className, children, ...props }) => (
    <tr
      {...props}
      className={[
        "border-b border-[#EEF2F7] last:border-b-0",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </tr>
  ),
  td: ({ className, children, ...props }) => (
    <td
      {...props}
      className={[
        "px-4 py-3 align-top text-[14px] leading-6 text-slate-600",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </td>
  ),
  pre: ({ children }) => {
    const codeEl = Children.toArray(children).find((c) =>
      isValidElement<{ className?: string }>(c),
    );
    const cls =
      codeEl && isValidElement<{ className?: string }>(codeEl)
        ? codeEl.props.className
        : undefined;
    const langMatch = /language-(\w+)/.exec(cls || "");
    return (
      <CodeBlock
        code={extractTextContent(children).replace(/\n$/, "")}
        language={langMatch ? langMatch[1] : undefined}
      />
    );
  },
  code: ({ className, children, ...props }) => {
    if (className?.includes("language-")) {
      return (
        <code {...props} className={className}>
          {children}
        </code>
      );
    }
    return (
      <code
        {...props}
        className={[
          "rounded-lg bg-[#EFF4FF] px-1.5 py-0.5 font-mono text-[0.92em] text-[#3767D6]",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {children}
      </code>
    );
  },
  };
}

const defaultMarkdownComponents = buildMarkdownComponents();

/* ------------------------------------------------------------------ */
/*  Markdown content — plain & streaming-optimised variants            */
/* ------------------------------------------------------------------ */

export function MarkdownContent({
  content,
  onOpenArtifact,
}: {
  content: string;
  onOpenArtifact?: (artifact: Artifact) => void;
}) {
  const components = useMemo(
    () => (onOpenArtifact ? buildMarkdownComponents(onOpenArtifact) : defaultMarkdownComponents),
    [onOpenArtifact],
  );

  return (
    <div className="min-w-0 max-w-none">
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

const MemoizedMarkdown = memo(MarkdownContent);

/**
 * During streaming the content grows token-by-token.  We split at the last
 * stable paragraph break so `MemoizedMarkdown` can skip re-parsing everything
 * before that boundary — only the dynamic tail re-renders per delta.
 */
function StreamingMarkdownContent({
  content,
  streaming,
  onOpenArtifact,
}: {
  content: string;
  streaming?: boolean;
  onOpenArtifact?: (artifact: Artifact) => void;
}) {
  if (!streaming || !content) {
    return <MarkdownContent content={content} onOpenArtifact={onOpenArtifact} />;
  }

  const bp = findLastStableBreak(content);
  const stable = content.slice(0, bp);
  const tail = content.slice(bp);

  return (
    <div className="min-w-0 max-w-none">
      {stable && <MemoizedMarkdown content={stable} onOpenArtifact={onOpenArtifact} />}
      {tail && <MarkdownContent content={tail} onOpenArtifact={onOpenArtifact} />}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Thinking Block                                                    */
/* ------------------------------------------------------------------ */

function ThinkingBlock({
  content,
  isThinking,
}: {
  content: string;
  isThinking: boolean;
}) {
  const [manualToggle, setManualToggle] = useState<boolean | null>(null);
  const expanded = manualToggle !== null ? manualToggle : isThinking;

  if (!content) return null;

  return (
    <div className="mb-3 overflow-hidden rounded-2xl border border-violet-200/60 bg-gradient-to-b from-violet-50/80 to-violet-50/30">
      <button
        type="button"
        onClick={() =>
          setManualToggle((prev) =>
            prev === null ? !isThinking : !prev,
          )
        }
        className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left transition-colors hover:bg-violet-50"
      >
        <span className="text-violet-400">
          {expanded ? (
            <ChevronDown size={14} />
          ) : (
            <ChevronRight size={14} />
          )}
        </span>
        {isThinking ? (
          <LoaderCircle
            size={14}
            className="animate-spin text-violet-500"
          />
        ) : (
          <Brain size={14} className="text-violet-500" />
        )}
        <span className="text-[13px] font-medium text-violet-700">
          {isThinking ? "正在思考…" : "思考过程"}
        </span>
        {!isThinking && (
          <span className="text-[11px] text-violet-400">
            {content.length} 字
          </span>
        )}
      </button>

      {expanded && (
        <div className="border-t border-violet-100 px-4 py-3">
          <p className="whitespace-pre-wrap text-[13px] leading-6 text-violet-900/70">
            {content}
          </p>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  ToolCallGroup — Cursor-style collapsible summary                   */
/* ------------------------------------------------------------------ */

function buildToolSummary(blocks: ToolBlock[]): string {
  const groups = new Map<string, number>();
  for (const b of blocks) {
    const name = cleanName(b.name);
    groups.set(name, (groups.get(name) || 0) + 1);
  }
  const parts: string[] = [];
  for (const [name, count] of groups) {
    parts.push(count > 1 ? `${name} x${count}` : name);
  }
  return parts.join(", ");
}

function ToolCallGroup({
  blocks,
  onOpenArtifact,
}: {
  blocks: ToolBlock[];
  onOpenArtifact?: (artifact: Artifact) => void;
}) {
  const hasRunning = blocks.some((b) => b.status === "running");
  const [manualToggle, setManualToggle] = useState<boolean | null>(null);
  const expanded = manualToggle !== null ? manualToggle : hasRunning;

  const successCount = useMemo(
    () => blocks.filter((b) => b.status === "success").length,
    [blocks],
  );
  const errorCount = useMemo(
    () => blocks.filter((b) => b.status === "error").length,
    [blocks],
  );
  const summary = useMemo(() => buildToolSummary(blocks), [blocks]);

  return (
    <div className="mt-4">
      <button
        type="button"
        onClick={() =>
          setManualToggle((prev) =>
            prev === null ? !hasRunning : !prev,
          )
        }
        className="flex w-full items-center gap-2.5 rounded-xl border border-[#E7ECF3] bg-[#FCFDFF] px-3.5 py-2 text-left transition-colors hover:border-[#DCE7FF] hover:bg-white"
      >
        <span className="inline-flex size-5 flex-shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-500">
          {hasRunning ? (
            <LoaderCircle size={12} className="animate-spin" />
          ) : (
            <Wrench size={12} />
          )}
        </span>

        <span className="min-w-0 flex-1 truncate text-[13px] text-slate-600">
          {hasRunning ? (
            <span className="font-medium text-slate-700">
              正在执行...
            </span>
          ) : (
            <>
              <span className="font-medium text-slate-700">
                执行了 {blocks.length} 个操作
              </span>
              <span className="ml-2 text-slate-400">{summary}</span>
            </>
          )}
        </span>

        <span className="flex flex-shrink-0 items-center gap-2">
          {!hasRunning && successCount > 0 && (
            <span className="inline-flex items-center gap-0.5 text-[11px] font-medium text-emerald-500">
              <CheckCircle2 size={11} />
              {successCount}
            </span>
          )}
          {!hasRunning && errorCount > 0 && (
            <span className="inline-flex items-center gap-0.5 text-[11px] font-medium text-rose-500">
              <TriangleAlert size={11} />
              {errorCount}
            </span>
          )}
          <span className="text-slate-300">
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>
        </span>
      </button>

      {expanded && (
        <div className="mt-2 space-y-2 pl-1">
          {blocks.map((block, index) => (
            <ToolBlockView key={index} block={block} onOpenArtifact={onOpenArtifact} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  MessageBubble                                                     */
/* ------------------------------------------------------------------ */

interface MessageBubbleProps {
  message: DisplayMessage;
  todos?: import("../types").TodoItem[];
  planStatus?: string;
  planReady?: boolean;
  planSlug?: string | null;
  onExecutePlan?: () => void;
  onDiscardPlan?: () => void;
  onRefinePlan?: () => void;
  onOpenArtifact?: (artifact: Artifact) => void;
}

export default function MessageBubble({ message, todos, planStatus, planReady, planSlug, onExecutePlan, onDiscardPlan, onRefinePlan, onOpenArtifact }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable */
    }
  }, [message.content]);

  const canCopy = Boolean(message.content.trim());
  const isThinking = Boolean(
    message.streaming && message.thinking && !message.content,
  );

  return (
    <div className="group/message space-y-2">
      <div
        className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}
      >
        <div className={`min-w-0 ${isUser ? "max-w-[78%]" : "w-full"}`}>
          {isUser ? (
            <div className="ml-auto rounded-[26px] border border-[#E7ECF3] bg-[#F3F5F9] px-5 py-3.5 text-[15px] leading-7 text-slate-700 shadow-[0_8px_24px_rgba(31,42,68,0.04)]">
              <UserMessageContent content={message.content} images={message.images} files={message.files} onOpenArtifact={onOpenArtifact} />
            </div>
          ) : (
            <div className="max-w-[860px] text-[15px] leading-7 text-slate-700">
              {/* Thinking block (visible when model emits reasoning tokens) */}
              {message.thinking && (
                <ThinkingBlock
                  content={message.thinking}
                  isThinking={isThinking}
                />
              )}

              {/* Plan mode: full PlanView from content */}
              {message.isPlan ? (
                <div className="mt-3">
                  <PlanView
                    content={message.content}
                    streaming={message.streaming}
                    todos={todos}
                    planStatus={planStatus}
                    planReady={planReady}
                    planSlug={planSlug}
                    onExecutePlan={onExecutePlan}
                    onDiscardPlan={onDiscardPlan}
                    onRefinePlan={onRefinePlan}
                    onOpenArtifact={onOpenArtifact}
                  />
                </div>
              ) : message.steps.length > 0 ? (
                <>
                  {message.steps.map((step, i) =>
                    step.type === "text" ? (
                      <StreamingMarkdownContent
                        key={i}
                        content={step.content}
                        streaming={
                          i === message.steps.length - 1 &&
                          !!message.streaming
                        }
                        onOpenArtifact={onOpenArtifact}
                      />
                    ) : (
                      <ToolCallGroup
                        key={i}
                        blocks={step.blocks}
                        onOpenArtifact={onOpenArtifact}
                      />
                    ),
                  )}
                </>
              ) : message.streaming ? (
                message.thinking ? null : (
                  <div className="inline-flex items-center gap-1.5 rounded-2xl border border-[#E7ECF3] bg-white px-5 py-3 shadow-[0_4px_12px_rgba(31,42,68,0.04)]">
                    <span className="typing-dot h-1.5 w-1.5 rounded-full bg-[#4C84FF]/50" />
                    <span className="typing-dot h-1.5 w-1.5 rounded-full bg-[#4C84FF]/50" />
                    <span className="typing-dot h-1.5 w-1.5 rounded-full bg-[#4C84FF]/50" />
                  </div>
                )
              ) : (
                <StreamingMarkdownContent
                  content={message.content}
                  streaming={false}
                  onOpenArtifact={onOpenArtifact}
                />
              )}
            </div>
          )}
        </div>
      </div>

      {canCopy && (
        <div
          className={`flex items-center ${
            isUser ? "justify-end pr-1" : "justify-start"
          } ${
            isUser
              ? "pointer-events-none opacity-0 transition-opacity duration-150 group-hover/message:pointer-events-auto group-hover/message:opacity-100"
              : ""
          }`}
        >
          <button
            type="button"
            onClick={() => void handleCopy()}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition hover:bg-[#F3F6FB] hover:text-slate-700"
            aria-label="复制消息"
            title="复制"
          >
            {copied ? (
              <Check className="h-4 w-4" />
            ) : (
              <Copy className="h-4 w-4" />
            )}
          </button>
        </div>
      )}
    </div>
  );
}

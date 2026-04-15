import { useState, type ReactNode } from "react";
import {
  X,
  Image as ImageIcon,
  FileText,
  FileCode,
  FileSpreadsheet,
  File,
  Loader2,
} from "lucide-react";
import { getBaseUrl } from "../services/api";

// ---------------------------------------------------------------------------
// File category system — extensible for future file types
// ---------------------------------------------------------------------------

export type FileCategory = "image" | "code" | "document" | "spreadsheet" | "other";

const IMAGE_EXTS = new Set([
  ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico",
]);
const CODE_EXTS = new Set([
  ".js", ".ts", ".tsx", ".jsx", ".py", ".java", ".cpp", ".c", ".h",
  ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".cs", ".vue", ".svelte",
  ".html", ".css", ".scss", ".less", ".sql", ".sh", ".bat",
]);
const DOC_EXTS = new Set([
  ".md", ".txt", ".pdf", ".doc", ".docx", ".log",
]);
const SPREADSHEET_EXTS = new Set([
  ".xlsx", ".xls", ".csv", ".tsv",
]);
const CONVERTIBLE_EXTS = new Set([
  ...DOC_EXTS, ...SPREADSHEET_EXTS,
  ".json", ".xml", ".yaml", ".yml", ".toml",
]);

export function classifyFile(path: string): FileCategory {
  const dot = path.lastIndexOf(".");
  if (dot < 0) return "other";
  const ext = path.slice(dot).toLowerCase();
  if (IMAGE_EXTS.has(ext)) return "image";
  if (SPREADSHEET_EXTS.has(ext)) return "spreadsheet";
  if (DOC_EXTS.has(ext)) return "document";
  if (CODE_EXTS.has(ext)) return "code";
  return "other";
}

export function isPreviewable(category: FileCategory): boolean {
  return category === "image";
}

export function isConvertible(path: string): boolean {
  const dot = path.lastIndexOf(".");
  if (dot < 0) return false;
  return CONVERTIBLE_EXTS.has(path.slice(dot).toLowerCase());
}

// ---------------------------------------------------------------------------
// FileAttachment
// ---------------------------------------------------------------------------

export type AttachmentStatus = "ready" | "processing" | "error";

export interface FileAttachment {
  display: string;
  actual: string;
  category: FileCategory;
  previewUrl: string | null;
  status: AttachmentStatus;
  fileId?: string;
  preview?: string;
  meta?: Record<string, unknown>;
  errorMsg?: string;
}

export function buildFileAttachment(
  display: string,
  actual: string,
): FileAttachment {
  const category = classifyFile(actual);
  const previewUrl = isPreviewable(category)
    ? `${getBaseUrl()}/api/file-preview?path=${encodeURIComponent(actual)}`
    : null;
  return {
    display,
    actual,
    category,
    previewUrl,
    status: isConvertible(actual) ? "processing" : "ready",
  };
}

// ---------------------------------------------------------------------------
// Category-specific icons
// ---------------------------------------------------------------------------

const CATEGORY_ICON: Record<FileCategory, ReactNode> = {
  image: <ImageIcon size={14} className="flex-shrink-0" />,
  code: <FileCode size={14} className="flex-shrink-0" />,
  document: <FileText size={14} className="flex-shrink-0" />,
  spreadsheet: <FileSpreadsheet size={14} className="flex-shrink-0" />,
  other: <File size={14} className="flex-shrink-0" />,
};

const CATEGORY_ICON_LG: Record<FileCategory, ReactNode> = {
  image: <ImageIcon size={20} className="flex-shrink-0" />,
  code: <FileCode size={20} className="flex-shrink-0" />,
  document: <FileText size={20} className="flex-shrink-0" />,
  spreadsheet: <FileSpreadsheet size={20} className="flex-shrink-0" />,
  other: <File size={20} className="flex-shrink-0" />,
};

function formatFileSize(bytes: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ---------------------------------------------------------------------------
// Preview renderers
// ---------------------------------------------------------------------------

interface AttachmentPreviewProps {
  attachment: FileAttachment;
  onRemove: () => void;
  disabled?: boolean;
}

function ImagePreview({ attachment, onRemove, disabled }: AttachmentPreviewProps) {
  const [failed, setFailed] = useState(false);

  return (
    <div className="group relative inline-flex flex-col items-center">
      <div className="relative overflow-hidden rounded-2xl border border-[#DCE7FF] bg-[#F8FAFF] shadow-[0_2px_8px_rgba(76,132,255,0.08)]">
        {attachment.previewUrl && !failed ? (
          <img
            src={attachment.previewUrl}
            alt={attachment.display}
            onError={() => setFailed(true)}
            className="h-[100px] w-auto max-w-[160px] object-cover"
            loading="lazy"
          />
        ) : (
          <div className="flex h-[100px] w-[100px] items-center justify-center text-slate-300">
            <ImageIcon size={32} />
          </div>
        )}
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled}
          className="absolute right-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-black/50 text-white opacity-0 transition-opacity group-hover:opacity-100 hover:bg-black/70 disabled:pointer-events-none"
          aria-label={`Remove ${attachment.display}`}
        >
          <X size={12} />
        </button>
      </div>
      <span
        className="mt-1 max-w-[160px] truncate text-[11px] text-slate-400"
        title={attachment.actual}
      >
        {attachment.display.split("/").pop()}
      </span>
    </div>
  );
}

function DocumentPreview({ attachment, onRemove, disabled }: AttachmentPreviewProps) {
  const filename = attachment.actual.split("/").pop() ?? attachment.display;
  const isLoading = attachment.status === "processing";
  const hasError = attachment.status === "error";

  const metaLabel = (() => {
    if (isLoading) return "转换中…";
    if (hasError) return attachment.errorMsg || "转换失败";
    const m = attachment.meta;
    if (!m) return "";
    const parts: string[] = [];
    if (m.size) parts.push(formatFileSize(m.size as number));
    if (m.sheet_count) parts.push(`${m.sheet_count} 个工作表`);
    if (m.total_rows) parts.push(`${m.total_rows} 行`);
    if (m.word_count) parts.push(`${m.word_count} 词`);
    return parts.join(" · ");
  })();

  return (
    <div
      className={`group relative inline-flex items-center gap-2 rounded-2xl border px-3 py-2 ${
        hasError
          ? "border-red-200 bg-red-50/60"
          : attachment.category === "spreadsheet"
          ? "border-emerald-200 bg-emerald-50/60"
          : "border-blue-200 bg-blue-50/60"
      }`}
    >
      <div
        className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg ${
          hasError
            ? "bg-red-100 text-red-400"
            : attachment.category === "spreadsheet"
            ? "bg-emerald-100 text-emerald-600"
            : "bg-blue-100 text-blue-500"
        }`}
      >
        {isLoading ? (
          <Loader2 size={18} className="animate-spin" />
        ) : (
          CATEGORY_ICON_LG[attachment.category]
        )}
      </div>
      <div className="min-w-0">
        <p className="max-w-[200px] truncate text-[13px] font-medium text-slate-700" title={attachment.actual}>
          {filename}
        </p>
        {metaLabel && (
          <p className={`text-[11px] ${hasError ? "text-red-400" : "text-slate-400"}`}>
            {metaLabel}
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={onRemove}
        disabled={disabled}
        className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-slate-300 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-slate-200 hover:text-slate-500 disabled:pointer-events-none"
        aria-label={`Remove ${attachment.display}`}
      >
        <X size={12} />
      </button>
    </div>
  );
}

function GenericPreview({ attachment, onRemove, disabled }: AttachmentPreviewProps) {
  return (
    <span
      className="inline-flex max-w-full items-center gap-1 rounded-full border border-[#DCE7FF] bg-[#EFF4FF] px-2.5 py-1 text-xs text-[#3767D6]"
      title={attachment.actual}
    >
      {CATEGORY_ICON[attachment.category]}
      <span className="min-w-0 max-w-[340px] truncate">@{attachment.display}</span>
      <button
        type="button"
        className="rounded-full p-0.5 transition-colors hover:bg-[#DCE7FF]"
        onClick={onRemove}
        disabled={disabled}
        aria-label={`Remove ${attachment.display}`}
      >
        <X size={12} />
      </button>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Registry — add new renderers here for future file types
// ---------------------------------------------------------------------------

type PreviewRenderer = (props: AttachmentPreviewProps) => ReactNode;

const PREVIEW_RENDERERS: Record<FileCategory, PreviewRenderer> = {
  image: (props) => <ImagePreview {...props} />,
  code: (props) => <GenericPreview {...props} />,
  document: (props) => <DocumentPreview {...props} />,
  spreadsheet: (props) => <DocumentPreview {...props} />,
  other: (props) => <GenericPreview {...props} />,
};

export default function AttachmentPreview(props: AttachmentPreviewProps) {
  const render = PREVIEW_RENDERERS[props.attachment.category];
  return <>{render(props)}</>;
}

// ---------------------------------------------------------------------------
// AttachmentList — layout container
// ---------------------------------------------------------------------------

interface AttachmentListProps {
  attachments: FileAttachment[];
  onRemove: (actual: string) => void;
  disabled?: boolean;
}

export function AttachmentList({ attachments, onRemove, disabled }: AttachmentListProps) {
  if (!attachments.length) return null;

  const images = attachments.filter((a) => a.category === "image");
  const docs = attachments.filter(
    (a) => a.category === "document" || a.category === "spreadsheet",
  );
  const others = attachments.filter(
    (a) => a.category !== "image" && a.category !== "document" && a.category !== "spreadsheet",
  );

  return (
    <div className="space-y-2 pb-3">
      {images.length > 0 && (
        <div className="flex flex-wrap gap-2.5">
          {images.map((a) => (
            <AttachmentPreview key={a.actual} attachment={a} onRemove={() => onRemove(a.actual)} disabled={disabled} />
          ))}
        </div>
      )}
      {docs.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {docs.map((a) => (
            <AttachmentPreview key={a.actual} attachment={a} onRemove={() => onRemove(a.actual)} disabled={disabled} />
          ))}
        </div>
      )}
      {others.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {others.map((a) => (
            <AttachmentPreview key={a.actual} attachment={a} onRemove={() => onRemove(a.actual)} disabled={disabled} />
          ))}
        </div>
      )}
    </div>
  );
}

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  FileText,
  ImageIcon,
  X,
} from "lucide-react";
import { MarkdownContent } from "./MessageBubble";
import type { Artifact } from "../types";

const PANEL_MIN_W = 280;
const PANEL_MAX_W = 800;
const PANEL_DEFAULT_W = 420;

function getFileExtension(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  return dot >= 0 ? fileName.slice(dot).toLowerCase() : "";
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [header, b64] = dataUrl.split(",");
  const mime =
    header.match(/data:([^;]+)/)?.[1] ?? "application/octet-stream";
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

/* ------------------------------------------------------------------ */
/*  Sub-previews                                                       */
/* ------------------------------------------------------------------ */

function PdfPreview({ dataUrl }: { dataUrl: string }) {
  const blobUrl = useMemo(() => {
    const blob = dataUrlToBlob(dataUrl);
    return URL.createObjectURL(blob);
  }, [dataUrl]);

  useEffect(() => {
    return () => URL.revokeObjectURL(blobUrl);
  }, [blobUrl]);

  return (
    <iframe
      src={blobUrl}
      title="PDF 预览"
      className="h-full w-full border-0"
    />
  );
}

function DocxPreview({ dataUrl }: { dataUrl: string }) {
  const [html, setHtml] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mammoth = await import("mammoth");
        const blob = dataUrlToBlob(dataUrl);
        const arrayBuffer = await blob.arrayBuffer();
        const result = await mammoth.convertToHtml({ arrayBuffer });
        if (!cancelled) setHtml(result.value);
      } catch {
        if (!cancelled) setError("无法解析 Word 文档");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [dataUrl]);

  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (!html)
    return <p className="text-sm text-slate-400">正在解析文档…</p>;

  return (
    <div
      className="prose prose-sm max-w-none text-slate-700 prose-headings:text-slate-800 prose-strong:text-slate-700 prose-table:border-collapse prose-th:border prose-th:border-[#E7ECF3] prose-th:bg-[#F8FAFF] prose-th:px-3 prose-th:py-1.5 prose-td:border prose-td:border-[#E7ECF3] prose-td:px-3 prose-td:py-1.5"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function XlsxPreview({ dataUrl }: { dataUrl: string }) {
  const [sheets, setSheets] = useState<
    { name: string; rows: string[][] }[]
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [activeSheet, setActiveSheet] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const XLSX = await import("xlsx");
        const blob = dataUrlToBlob(dataUrl);
        const arrayBuffer = await blob.arrayBuffer();
        const workbook = XLSX.read(arrayBuffer, { type: "array" });
        const parsed = workbook.SheetNames.map((name) => {
          const sheet = workbook.Sheets[name];
          const rows = XLSX.utils.sheet_to_json<string[]>(sheet, {
            header: 1,
            defval: "",
          });
          return { name, rows: rows as string[][] };
        });
        if (!cancelled) {
          setSheets(parsed);
          setActiveSheet(0);
        }
      } catch {
        if (!cancelled) setError("无法解析 Excel 文件");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [dataUrl]);

  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (sheets.length === 0)
    return <p className="text-sm text-slate-400">正在解析表格…</p>;

  const current = sheets[activeSheet];

  return (
    <div className="space-y-3">
      {sheets.length > 1 && (
        <div className="flex flex-wrap gap-1">
          {sheets.map((s, i) => (
            <button
              key={s.name}
              type="button"
              className={`rounded-md px-2.5 py-1 text-xs transition ${
                i === activeSheet
                  ? "bg-[#4C84FF] text-white"
                  : "bg-[#F3F6FB] text-slate-500 hover:bg-[#E7ECF3]"
              }`}
              onClick={() => setActiveSheet(i)}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <tbody>
            {current?.rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    className={`border border-[#E7ECF3] px-2.5 py-1.5 text-slate-600 ${
                      ri === 0
                        ? "bg-[#F8FAFF] font-medium text-slate-700"
                        : ""
                    }`}
                  >
                    {String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Panel                                                         */
/* ------------------------------------------------------------------ */

interface ArtifactPanelProps {
  artifact: Artifact | null;
  visible: boolean;
  onClose: () => void;
}

export default function ArtifactPanel({
  artifact,
  visible,
  onClose,
}: ArtifactPanelProps) {
  const isImage = artifact?.contentType === "image";
  const ext = artifact ? getFileExtension(artifact.fileName) : "";
  const hasNativePreview = Boolean(
    artifact?.fileDataUrl &&
      [".pdf", ".docx", ".doc", ".xlsx"].includes(ext),
  );
  const isMarkdown = [".md", ".markdown"].includes(ext);

  const [panelWidth, setPanelWidth] = useState(PANEL_DEFAULT_W);
  const draggingRef = useRef(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);

  useEffect(() => {
    if (!visible) return;
    const onMouseMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      const delta = startXRef.current - e.clientX;
      const newW = Math.min(
        PANEL_MAX_W,
        Math.max(PANEL_MIN_W, startWidthRef.current + delta),
      );
      setPanelWidth(newW);
    };
    const onMouseUp = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [visible]);

  const handleResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      draggingRef.current = true;
      startXRef.current = e.clientX;
      startWidthRef.current = panelWidth;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    },
    [panelWidth],
  );

  function renderContent() {
    if (!artifact) return null;

    if (isImage) {
      return (
        <img
          src={artifact.content}
          alt={artifact.fileName}
          className="mx-auto max-w-full rounded-lg border border-[#E7ECF3] object-contain"
        />
      );
    }

    if (artifact.fileDataUrl) {
      if (ext === ".pdf") {
        return <PdfPreview dataUrl={artifact.fileDataUrl} />;
      }
      if (ext === ".docx" || ext === ".doc") {
        return <DocxPreview dataUrl={artifact.fileDataUrl} />;
      }
      if (ext === ".xlsx") {
        return <XlsxPreview dataUrl={artifact.fileDataUrl} />;
      }
    }

    if (isMarkdown) {
      return <MarkdownContent content={artifact.content} />;
    }

    return (
      <pre className="whitespace-pre-wrap break-words text-[13px] leading-6 text-slate-600">
        {artifact.content}
      </pre>
    );
  }

  const isPdf = ext === ".pdf" && artifact?.fileDataUrl;

  return (
    <div
      className={`shrink-0 overflow-hidden ${
        !draggingRef.current
          ? "transition-[width,opacity] duration-300 ease-in-out"
          : ""
      } ${visible ? "opacity-100" : "w-0 opacity-0"}`}
      style={visible ? { width: panelWidth } : undefined}
    >
      <div
        className="relative flex h-full flex-col border-l border-[#E7ECF3] bg-white"
        style={{ width: panelWidth, minWidth: PANEL_MIN_W }}
      >
        {/* resize handle */}
        <div
          className="absolute inset-y-0 left-0 z-10 w-1 cursor-col-resize hover:bg-[#4C84FF]/20 active:bg-[#4C84FF]/30"
          onMouseDown={handleResizeStart}
        />

        {/* header */}
        <div className="flex shrink-0 items-center gap-2.5 border-b border-[#EEF2F7] px-4 py-3">
          {isImage ? (
            <ImageIcon className="h-4 w-4 shrink-0 text-[#4C84FF]" />
          ) : (
            <FileText className="h-4 w-4 shrink-0 text-[#4C84FF]" />
          )}
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-700">
            {artifact?.fileName}
          </span>
          {hasNativePreview && (
            <span className="shrink-0 rounded bg-[#EFF4FF] px-1.5 py-0.5 text-[10px] text-[#4C84FF]">
              原始格式
            </span>
          )}
          <button
            type="button"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-[#F3F6FB] hover:text-slate-600"
            onClick={onClose}
            aria-label="关闭预览"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* body */}
        {isPdf ? (
          <div className="min-h-0 flex-1">{renderContent()}</div>
        ) : (
          <div className="min-h-0 flex-1 overflow-auto p-5">
            {renderContent()}
          </div>
        )}
      </div>
    </div>
  );
}

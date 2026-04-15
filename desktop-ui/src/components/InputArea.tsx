import { useRef, useCallback, useEffect, useState } from "react";
import { Send, Square, X, FileText, Lightbulb, Check } from "lucide-react";
import * as api from "../services/api";
import PermissionModeToggle from "./PermissionModeToggle";
import {
  AttachmentList,
  buildFileAttachment,
  isConvertible,
  type FileAttachment,
} from "./AttachmentPreview";

interface InputAreaProps {
  busy: boolean;
  sessionId: string;
  onSend: (text: string) => void;
  onCancel: () => void;
  conversationMode?: "normal" | "plan";
  planReady?: boolean;
  onTogglePlanMode?: () => void;
  planSuggestion?: string | null;
  onAcceptPlanSuggestion?: () => void;
  onDismissPlanSuggestion?: () => void;
}

declare global {
  interface Window {
    pywebview?: {
      platform?: string;
      api?: {
        resolve_dropped_files?: (payload: {
          files: Array<{ name: string }>;
        }) => Promise<string[]>;
      };
    };
    chrome?: {
      webview?: {
        postMessageWithAdditionalObjects?: (
          message: string,
          additionalObjects: FileList | File[]
        ) => void;
      };
    };
  }
}

export default function InputArea({
  busy,
  sessionId,
  onSend,
  onCancel,
  conversationMode = "normal",
  planReady = false,
  onTogglePlanMode,
  planSuggestion = null,
  onAcceptPlanSuggestion,
  onDismissPlanSuggestion,
}: InputAreaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<FileAttachment[]>([]);
  const [draggingFiles, setDraggingFiles] = useState(false);
  const [workspaceRoot, setWorkspaceRoot] = useState("");

  const normalizePath = useCallback((p: string) => p.replace(/\\/g, "/"), []);

  const toDisplayPath = useCallback(
    (rawPath: string) => {
      const path = normalizePath(rawPath).trim();
      if (!path) return path;
      if (!workspaceRoot) return path;

      const root = normalizePath(workspaceRoot).replace(/\/+$/, "");
      const lowerPath = path.toLowerCase();
      const lowerRoot = root.toLowerCase();
      if (lowerPath === lowerRoot) return ".";
      if (lowerPath.startsWith(`${lowerRoot}/`)) {
        return path.slice(root.length + 1);
      }
      return path;
    },
    [normalizePath, workspaceRoot]
  );

  const decodeFileUri = useCallback((uri: string): string | null => {
    if (!uri.startsWith("file://")) return null;
    try {
      const url = new URL(uri);
      let pathname = decodeURIComponent(url.pathname || "");
      if (/^\/[a-zA-Z]:\//.test(pathname)) pathname = pathname.slice(1);
      if (url.host && !/^[a-zA-Z]:$/.test(url.host)) {
        pathname = `//${url.host}${pathname}`;
      }
      return pathname;
    } catch {
      return null;
    }
  }, []);

  const looksLikePath = useCallback((s: string) => {
    const t = s.trim();
    return /^[a-zA-Z]:[\\/]/.test(t) || /^\\\\/.test(t) || t.startsWith("/");
  }, []);

  const parsePathsFromText = useCallback(
    (value: string): string[] => {
      const out: string[] = [];
      for (const line of value.split(/\r?\n/)) {
        const item = line.trim().replace(/^['"]|['"]$/g, "");
        if (!item || item.startsWith("#")) continue;
        const decoded = decodeFileUri(item);
        if (decoded) {
          out.push(decoded);
          continue;
        }
        if (looksLikePath(item)) out.push(item);
      }
      return out;
    },
    [decodeFileUri, looksLikePath]
  );

  const uniqueByKey = useCallback((rows: FileAttachment[]) => {
    const seen = new Set<string>();
    const out: FileAttachment[] = [];
    for (const row of rows) {
      const key = row.actual.toLowerCase();
      if (!row.actual || seen.has(key)) continue;
      seen.add(key);
      out.push(row);
    }
    return out;
  }, []);

  const buildChip = useCallback(
    (rawPath: string): FileAttachment | null => {
      const actual = normalizePath(rawPath).trim();
      if (!actual) return null;
      const display = toDisplayPath(actual);
      return buildFileAttachment(display || actual, actual);
    },
    [normalizePath, toDisplayPath]
  );

  const buildChips = useCallback(
    (rawPaths: string[]): FileAttachment[] => {
      const chips = rawPaths
        .map((p) => buildChip(p))
        .filter((x): x is FileAttachment => x !== null);
      return uniqueByKey(chips);
    },
    [buildChip, uniqueByKey]
  );

  const extractDroppedMentions = useCallback(
    (data: DataTransfer): FileAttachment[] => {
      const rawPaths: string[] = [];

      const uriList = data.getData("text/uri-list");
      if (uriList) rawPaths.push(...parsePathsFromText(uriList));

      const plainText = data.getData("text/plain");
      if (plainText) rawPaths.push(...parsePathsFromText(plainText));

      const files = Array.from(data.files || []);
      for (const file of files) {
        const path = (file as File & { path?: string }).path;
        if (path) {
          rawPaths.push(path);
          continue;
        }
        if (file.webkitRelativePath) {
          rawPaths.push(file.webkitRelativePath);
          continue;
        }
        rawPaths.push(file.name);
      }

      return buildChips(rawPaths);
    },
    [buildChips, parsePathsFromText]
  );

  const resolveDroppedMentions = useCallback(
    async (e: React.DragEvent<HTMLDivElement>): Promise<FileAttachment[]> => {
      const apiBridge = window.pywebview?.api?.resolve_dropped_files;
      if (!apiBridge) {
        return extractDroppedMentions(e.dataTransfer);
      }

      const files = Array.from(e.dataTransfer.files || []).map((file) => ({
        name: file.name,
      }));

      try {
        if (
          window.pywebview?.platform === "edgechromium" &&
          window.chrome?.webview?.postMessageWithAdditionalObjects &&
          e.dataTransfer.files?.length
        ) {
          window.chrome.webview.postMessageWithAdditionalObjects(
            "FilesDropped",
            e.dataTransfer.files
          );
          await new Promise((resolve) => window.setTimeout(resolve, 40));
        }

        const resolved = await apiBridge({
          files,
        });
        if (Array.isArray(resolved) && resolved.length > 0) {
          return buildChips(resolved);
        }
      } catch {
        // Fall back to browser-exposed data when desktop resolution is unavailable.
      }

      return extractDroppedMentions(e.dataTransfer);
    },
    [buildChips, extractDroppedMentions]
  );

  const adjustHeight = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    }
  }, []);

  const handleSend = useCallback(() => {
    const body = text.trim();
    if ((!body && attachments.length === 0) || busy) return;

    const mentionLines = attachments.map((m) => `@${m.actual}`);
    const composed = mentionLines.length
      ? body
        ? `${mentionLines.join("\n")}\n${body}`
        : mentionLines.join("\n")
      : body;

    onSend(composed);
    setText("");
    setAttachments([]);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }, [busy, attachments, onSend, text]);

  const appendMentions = useCallback(
    (chips: FileAttachment[]) => {
      if (!chips.length) return;
      setAttachments((prev) => uniqueByKey([...prev, ...chips]));

      for (const chip of chips) {
        if (chip.status !== "processing" || !isConvertible(chip.actual)) continue;
        api
          .processFile(chip.actual, sessionId)
          .then((result) => {
            setAttachments((prev) =>
              prev.map((a) =>
                a.actual === chip.actual
                  ? {
                      ...a,
                      status: result.error ? "error" : "ready",
                      fileId: result.file_id,
                      preview: result.preview,
                      meta: {
                        size: result.size,
                        markdown_path: result.markdown_path,
                        ...result.meta,
                      },
                      errorMsg: result.error,
                    }
                  : a,
              ),
            );
          })
          .catch(() => {
            setAttachments((prev) =>
              prev.map((a) =>
                a.actual === chip.actual
                  ? { ...a, status: "error", errorMsg: "网络错误" }
                  : a,
              ),
            );
          });
      }

      requestAnimationFrame(() => {
        textareaRef.current?.focus();
        adjustHeight();
      });
    },
    [adjustHeight, uniqueByKey, sessionId]
  );

  const handleDrop = useCallback(
    async (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setDraggingFiles(false);
      const chips = await resolveDroppedMentions(e);
      appendMentions(chips);
    },
    [appendMentions, resolveDroppedMentions]
  );

  const handleDragOver = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      if (!draggingFiles) setDraggingFiles(true);
    },
    [draggingFiles]
  );

  const handleDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const next = e.relatedTarget as Node | null;
    if (next && e.currentTarget.contains(next)) return;
    setDraggingFiles(false);
  }, []);

  const removeMention = useCallback((targetActual: string) => {
    setAttachments((prev) => prev.filter((m) => m.actual !== targetActual));
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
        e.preventDefault();
        handleSend();
        return;
      }
      if (e.key === "Backspace" && !text && attachments.length > 0) {
        e.preventDefault();
        setAttachments((prev) => prev.slice(0, prev.length - 1));
      }
    },
    [handleSend, attachments.length, text]
  );

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  useEffect(() => {
    adjustHeight();
  }, [adjustHeight, text]);

  useEffect(() => {
    let active = true;
    api
      .getWorkspace()
      .then((ws) => {
        if (!active) return;
        setWorkspaceRoot(ws.workspace_root || "");
      })
      .catch(() => {
        // ignore; absolute path fallback still works
      });
    return () => {
      active = false;
    };
  }, []);

  const sendDisabled = busy || (!text.trim() && attachments.length === 0);

  return (
    <div className="flex-shrink-0 px-4 pb-5 pt-2 sm:px-5">
      <div className="mx-auto mb-3 flex w-full max-w-[920px] justify-end">
        <PermissionModeToggle />
      </div>
      <div className="mx-auto w-full max-w-[920px]">
        {/* Plan mode banner */}
        {conversationMode === "plan" && !planReady && !busy && (
          <div className="mb-2 flex items-center gap-2 rounded-2xl border border-blue-200/60 bg-gradient-to-r from-blue-50 to-indigo-50/50 px-4 py-2.5">
            <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-blue-500/10">
              <FileText size={13} className="text-blue-600" />
            </div>
            <p className="text-sm font-medium text-blue-800">
              计划模式
            </p>
            <p className="text-xs text-blue-500">
              AI 将只制定计划不执行，你可以审阅、修改后再决定是否执行
            </p>
          </div>
        )}
        <div
          className={`rounded-[30px] border bg-white shadow-[0_22px_56px_rgba(31,42,68,0.08)] transition-all ${
            draggingFiles
              ? "border-[#4C84FF] bg-[#F8FAFF] ring-4 ring-[#DCE7FF]"
              : "border-[#E7ECF3]"
          }`}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragEnter={handleDragOver}
          onDragLeave={handleDragLeave}
        >
          <div className="px-4 pb-0 pt-4 sm:px-5">
            {attachments.length > 0 && (
              <AttachmentList
                attachments={attachments}
                onRemove={removeMention}
                disabled={busy}
              />
            )}

            <textarea
              ref={textareaRef}
              value={text}
              rows={1}
              placeholder="继续追问...（也可以拖文件进来）"
              className="w-full min-h-[30px] max-h-[200px] resize-none border-0 bg-transparent px-1 py-0.5 text-[15px] leading-6 text-slate-700 outline-none placeholder:text-slate-400"
              onChange={(e) => setText(e.target.value)}
              onInput={adjustHeight}
              onKeyDown={handleKeyDown}
              disabled={busy}
            />
          </div>

          <div className="mt-2 flex items-center justify-between gap-3 border-t border-[#E7ECF3] px-4 pb-4 pt-3 sm:px-5">
            <div className="flex min-w-0 items-center gap-2">
              <button
                type="button"
                onClick={onTogglePlanMode}
                disabled={busy}
                title={conversationMode === "plan" ? "切换到执行模式" : "切换到计划模式"}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-all disabled:opacity-50 ${
                  conversationMode === "plan"
                    ? "border-amber-300 bg-amber-50 text-amber-700 shadow-[0_2px_8px_rgba(245,158,11,0.15)]"
                    : "border-[#E7ECF3] bg-white text-slate-500 hover:border-amber-200 hover:bg-amber-50 hover:text-amber-600"
                }`}
              >
                <FileText size={13} />
                {conversationMode === "plan" ? "计划模式" : "计划"}
              </button>
              <p className="min-w-0 truncate text-xs text-slate-500">
                {busy
                  ? "正在生成中，可随时停止"
                  : conversationMode === "plan"
                  ? "AI 将制定计划而不执行，你可以审阅后决定"
                  : "拖入文件可添加 @路径 · Enter 发送，Shift + Enter 换行"}
              </p>
            </div>

            {busy ? (
              <button
                onClick={onCancel}
                className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full border border-amber-200 bg-amber-50 text-amber-600 transition-colors hover:bg-amber-100"
                title="停止"
              >
                <Square size={16} className="fill-current" />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={sendDisabled}
                className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full border border-transparent bg-[#4C84FF] text-white shadow-[0_10px_30px_rgba(76,132,255,0.22)] transition-colors hover:bg-[#3F76EE] disabled:border-[#E7ECF3] disabled:bg-[#EFF4FF] disabled:text-slate-400"
                title="发送"
              >
                <Send size={16} />
              </button>
            )}
          </div>

          {planSuggestion && conversationMode !== "plan" && (
            <div className="flex items-center justify-between gap-3 border-t border-blue-200 bg-blue-50/60 px-4 pb-3 pt-3 sm:px-5">
              <div className="flex min-w-0 items-center gap-2">
                <Lightbulb size={16} className="flex-shrink-0 text-blue-500" />
                <p className="min-w-0 text-sm text-blue-800">
                  <span className="font-medium">AI 建议切换到计划模式：</span>{" "}
                  <span className="text-blue-600">{planSuggestion}</span>
                </p>
              </div>
              <div className="flex flex-shrink-0 items-center gap-2">
                <button
                  onClick={onDismissPlanSuggestion}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-50"
                >
                  <X size={12} />
                  忽略
                </button>
                <button
                  onClick={onAcceptPlanSuggestion}
                  className="inline-flex items-center gap-1 rounded-full border border-transparent bg-blue-500 px-3 py-1.5 text-xs font-medium text-white shadow-[0_4px_12px_rgba(59,130,246,0.25)] transition-colors hover:bg-blue-600"
                >
                  <Check size={12} />
                  切换到计划模式
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

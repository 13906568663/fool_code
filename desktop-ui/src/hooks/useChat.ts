import { useState, useCallback, useRef } from "react";
import type { DisplayMessage, TodoItem, WebEvent, AskUserQuestionItem } from "../types";
import * as api from "../services/api";
import { getBaseUrl } from "../services/api";

let messageIdCounter = 0;
function nextId(): string {
  return `msg-${Date.now()}-${++messageIdCounter}`;
}

function storedPathToImageUrl(storedPath: string): string | null {
  const raw = storedPath.replace(/\\/g, "/");
  const parts = raw.split("/");
  const filename = parts[parts.length - 1];
  const cacheIdx = parts.indexOf("image-cache");
  const sessionId =
    cacheIdx >= 0 && cacheIdx + 1 < parts.length - 1
      ? parts[cacheIdx + 1]
      : null;
  if (sessionId && filename) {
    return `${getBaseUrl()}/api/images/${sessionId}/${filename}`;
  }
  return null;
}

export function useChat() {
  const [displayMessages, setDisplayMessages] = useState<DisplayMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [permissionRequest, setPermissionRequest] = useState<{
    toolName: string;
    input: string;
  } | null>(null);
  const [askUserRequest, setAskUserRequest] = useState<{
    questions: AskUserQuestionItem[];
  } | null>(null);
  const [conversationMode, setConversationMode] = useState<"normal" | "plan">(
    "normal"
  );
  const [planReady, setPlanReady] = useState(false);
  const [planSuggestion, setPlanSuggestion] = useState<string | null>(null);
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [planSlug, setPlanSlug] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const assistantMsgRef = useRef<DisplayMessage | null>(null);
  const conversationModeRef = useRef(conversationMode);
  conversationModeRef.current = conversationMode;

  const sendMessageRef = useRef<
    (text: string, onDone?: () => void) => void
  >(() => {});

  const resetMessages = useCallback((initial: DisplayMessage[], initialTodos?: TodoItem[]) => {
    setDisplayMessages(initial);
    assistantMsgRef.current = null;
    setTodos(initialTodos ?? []);
  }, []);

  const sendMessage = useCallback(
    (text: string, onDone?: () => void) => {
      if (!text.trim() || busy) return;
      setBusy(true);

      const userMsg: DisplayMessage = {
        id: nextId(),
        role: "user",
        content: text,
        toolBlocks: [],
        steps: [],
      };

      const assistantMsg: DisplayMessage = {
        id: nextId(),
        role: "assistant",
        content: "",
        toolBlocks: [],
        steps: [],
        streaming: true,
        isPlan: conversationModeRef.current === "plan",
      };

      assistantMsgRef.current = assistantMsg;

      setDisplayMessages((prev) => [...prev, userMsg, assistantMsg]);

      const updateUser = (
        updater: (msg: DisplayMessage) => DisplayMessage
      ) => {
        setDisplayMessages((prev) =>
          prev.map((m) =>
            m.id === userMsg.id ? updater({ ...m }) : m
          )
        );
      };

      const updateAssistant = (
        updater: (msg: DisplayMessage) => DisplayMessage
      ) => {
        setDisplayMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id ? updater({ ...m }) : m
          )
        );
      };

      const controller = api.streamChat(
        text,
        (event: WebEvent) => {
          switch (event.type) {
            case "text":
              updateAssistant((m) => {
                const steps = [...m.steps];
                const last = steps[steps.length - 1];
                if (last && last.type === "text") {
                  steps[steps.length - 1] = { ...last, content: last.content + event.content };
                } else {
                  steps.push({ type: "text", content: event.content });
                }
                return { ...m, content: m.content + event.content, steps };
              });
              break;
            case "thinking":
              updateAssistant((m) => ({
                ...m,
                thinking: (m.thinking || "") + event.content,
              }));
              break;
            case "tool_start": {
              updateAssistant((m) => {
                const newBlock: import("../types").ToolBlock = {
                  type: "tool_start",
                  name: event.name,
                  input: event.input,
                  status: "running" as const,
                };
                const steps = [...m.steps];
                const last = steps[steps.length - 1];
                if (last && last.type === "tool_group") {
                  steps[steps.length - 1] = { ...last, blocks: [...last.blocks, newBlock] };
                } else {
                  steps.push({ type: "tool_group", blocks: [newBlock] });
                }
                return { ...m, toolBlocks: [...m.toolBlocks, newBlock], steps };
              });
              break;
            }
            case "tool_end":
              updateAssistant((m) => {
                const blocks = [...m.toolBlocks];
                const lastRunning = blocks
                  .slice()
                  .reverse()
                  .find((b) => b.status === "running");
                if (lastRunning) {
                  lastRunning.output = event.output;
                  lastRunning.error = event.error;
                  lastRunning.status = event.error ? "error" : "success";
                  lastRunning.type = "tool_end";
                }
                const steps = [...m.steps];
                for (let i = steps.length - 1; i >= 0; i--) {
                  const s = steps[i];
                  if (s.type === "tool_group") {
                    const sBlocks = [...s.blocks];
                    const runIdx = sBlocks.slice().reverse().findIndex((b) => b.status === "running");
                    if (runIdx >= 0) {
                      const realIdx = sBlocks.length - 1 - runIdx;
                      sBlocks[realIdx] = {
                        ...sBlocks[realIdx],
                        output: event.output,
                        error: event.error,
                        status: event.error ? "error" : "success",
                        type: "tool_end",
                      };
                      steps[i] = { ...s, blocks: sBlocks };
                    }
                    break;
                  }
                }
                return { ...m, toolBlocks: blocks, steps };
              });
              break;
            case "error":
              updateAssistant((m) => {
                const errText = `\n\n**错误:** ${event.content}`;
                const steps = [...m.steps];
                const last = steps[steps.length - 1];
                if (last && last.type === "text") {
                  steps[steps.length - 1] = { ...last, content: last.content + errText };
                } else {
                  steps.push({ type: "text", content: errText });
                }
                return { ...m, content: m.content + errText, steps };
              });
              break;
            case "permission_request":
              setPermissionRequest({
                toolName: event.tool_name,
                input: event.input,
              });
              break;
            case "hook_start":
              updateAssistant((m) => {
                const newBlock: import("../types").ToolBlock = {
                  type: "tool_start",
                  name: `hook:${event.name}`,
                  input: "正在校验...",
                  status: "running" as const,
                };
                const steps = [...m.steps];
                const last = steps[steps.length - 1];
                if (last && last.type === "tool_group") {
                  steps[steps.length - 1] = { ...last, blocks: [...last.blocks, newBlock] };
                } else {
                  steps.push({ type: "tool_group", blocks: [newBlock] });
                }
                return { ...m, toolBlocks: [...m.toolBlocks, newBlock], steps };
              });
              break;
            case "hook_end":
              updateAssistant((m) => {
                const blocks = [...m.toolBlocks];
                const lastRunning = blocks
                  .slice()
                  .reverse()
                  .find(
                    (b) =>
                      b.status === "running" && b.name.startsWith("hook:")
                  );
                if (lastRunning) {
                  lastRunning.output = event.output || "校验完成";
                  lastRunning.error = event.error;
                  lastRunning.status = event.error ? "error" : "success";
                  lastRunning.type = "tool_end";
                }
                const steps = [...m.steps];
                for (let i = steps.length - 1; i >= 0; i--) {
                  const s = steps[i];
                  if (s.type === "tool_group") {
                    const sBlocks = [...s.blocks];
                    const runIdx = sBlocks.slice().reverse().findIndex(
                      (b) => b.status === "running" && b.name.startsWith("hook:")
                    );
                    if (runIdx >= 0) {
                      const realIdx = sBlocks.length - 1 - runIdx;
                      sBlocks[realIdx] = {
                        ...sBlocks[realIdx],
                        output: event.output || "校验完成",
                        error: event.error,
                        status: event.error ? "error" : "success",
                        type: "tool_end",
                      };
                      steps[i] = { ...s, blocks: sBlocks };
                    }
                    break;
                  }
                }
                return { ...m, toolBlocks: blocks, steps };
              });
              break;
            case "background_status":
              break;
            case "mode_change":
              if (event.content === "plan" || event.content === "normal") {
                setConversationMode(event.content);
              }
              break;
            case "subagent_start":
              updateAssistant((m) => {
                const newBlock: import("../types").ToolBlock = {
                  type: "tool_start",
                  name: `子代理: ${event.content}`,
                  input: event.name,
                  status: "running" as const,
                };
                const steps = [...m.steps];
                const last = steps[steps.length - 1];
                if (last && last.type === "tool_group") {
                  steps[steps.length - 1] = { ...last, blocks: [...last.blocks, newBlock] };
                } else {
                  steps.push({ type: "tool_group", blocks: [newBlock] });
                }
                return { ...m, toolBlocks: [...m.toolBlocks, newBlock], steps };
              });
              break;
            case "subagent_end":
              updateAssistant((m) => {
                const blocks = [...m.toolBlocks];
                const last = blocks
                  .slice()
                  .reverse()
                  .find(
                    (b) =>
                      b.status === "running" && b.name.startsWith("子代理:")
                  );
                if (last) {
                  last.output = `状态: ${event.status}`;
                  last.status =
                    event.status === "completed" ? "success" : "error";
                  last.type = "tool_end";
                }
                const steps = [...m.steps];
                for (let i = steps.length - 1; i >= 0; i--) {
                  const s = steps[i];
                  if (s.type === "tool_group") {
                    const sBlocks = [...s.blocks];
                    const runIdx = sBlocks.slice().reverse().findIndex(
                      (b) => b.status === "running" && b.name.startsWith("子代理:")
                    );
                    if (runIdx >= 0) {
                      const realIdx = sBlocks.length - 1 - runIdx;
                      sBlocks[realIdx] = {
                        ...sBlocks[realIdx],
                        output: `状态: ${event.status}`,
                        status: event.status === "completed" ? "success" : "error",
                        type: "tool_end",
                      };
                      steps[i] = { ...s, blocks: sBlocks };
                    }
                    break;
                  }
                }
                return { ...m, toolBlocks: blocks, steps };
              });
              break;
            case "plan_mode_suggest":
              setPlanSuggestion(
                event.content || "AI 建议先制定计划再执行"
              );
              break;
            case "tool_progress":
              updateAssistant((m) => {
                const blocks = [...m.toolBlocks];
                const running = blocks
                  .slice()
                  .reverse()
                  .find(
                    (b) =>
                      b.status === "running" && b.name === event.name
                  );
                if (running) {
                  running.output =
                    (running.output || "") + event.content + "\n";
                }
                const steps = [...m.steps];
                for (let i = steps.length - 1; i >= 0; i--) {
                  const s = steps[i];
                  if (s.type === "tool_group") {
                    const sBlocks = [...s.blocks];
                    const runIdx = sBlocks.slice().reverse().findIndex(
                      (b) => b.status === "running" && b.name === event.name
                    );
                    if (runIdx >= 0) {
                      const realIdx = sBlocks.length - 1 - runIdx;
                      sBlocks[realIdx] = {
                        ...sBlocks[realIdx],
                        output: (sBlocks[realIdx].output || "") + event.content + "\n",
                      };
                      steps[i] = { ...s, blocks: sBlocks };
                    }
                    break;
                  }
                }
                return { ...m, toolBlocks: blocks, steps };
              });
              break;
            case "todo_update":
              try {
                const items: TodoItem[] = JSON.parse(event.content || "[]");
                setTodos(items);
              } catch {
                // ignore parse errors
              }
              break;
            case "image_stored": {
              const storedPath = (event as import("../types").ImageStoredEvent).content;
              const imgUrl = storedPathToImageUrl(storedPath);
              if (imgUrl) {
                updateUser((m) => ({
                  ...m,
                  images: [
                    ...(m.images || []),
                    { url: imgUrl, alt: "image" },
                  ],
                }));
              }
              break;
            }
            case "document_attached": {
              try {
                const info = JSON.parse(
                  (event as import("../types").DocumentAttachedEvent).content || "{}",
                );
                updateUser((m) => ({
                  ...m,
                  files: [
                    ...(m.files || []),
                    {
                      filename: info.filename || "file",
                      category: info.category || "document",
                      size: info.size || 0,
                      fileId: info.file_id || "",
                      markdownPath: info.markdown_path || undefined,
                      cachedPath: info.cached_path || undefined,
                    },
                  ],
                }));
              } catch {
                // ignore parse errors
              }
              break;
            }
            case "ask_user": {
              try {
                const payload = JSON.parse(
                  (event as import("../types").AskUserEvent).content || "{}",
                );
                const questions = payload.questions || [];
                if (questions.length > 0) {
                  setAskUserRequest({ questions });
                }
              } catch {
                // ignore parse errors
              }
              break;
            }
            case "plan_updated": {
              const slug = event.name;
              if (slug) setPlanSlug(slug);
              break;
            }
            case "compact_start":
              updateAssistant((m) => {
                const steps = [...m.steps];
                steps.push({ type: "text", content: "**⏳ 正在整理上下文...**" });
                return { ...m, steps };
              });
              break;
            case "compact_end":
              updateAssistant((m) => {
                const steps = m.steps.filter(
                  (s) => !(s.type === "text" && s.content === "**⏳ 正在整理上下文...**")
                );
                return { ...m, steps };
              });
              break;
            case "done":
              break;
          }
        },
        (error: Error) => {
          updateAssistant((m) => ({
            ...m,
            content: m.content + `\n\n**请求失败:** ${error.message}`,
            streaming: false,
          }));
          setBusy(false);
          onDone?.();
        },
        () => {
          updateAssistant((m) => ({ ...m, streaming: false }));
          setBusy(false);
          if (conversationModeRef.current === "plan") {
            setPlanReady(true);
          }
          onDone?.();
        }
      );

      abortRef.current = controller;
    },
    [busy]
  );

  sendMessageRef.current = sendMessage;

  const respondPermission = useCallback(async (decision: string) => {
    await api.sendPermissionDecision(decision);
    setPermissionRequest(null);
  }, []);

  const respondAskUser = useCallback(async (answers: Record<string, string>) => {
    await api.sendAskUserAnswer(answers);
    setAskUserRequest(null);
  }, []);

  const skipAskUser = useCallback(async () => {
    await api.sendAskUserAnswer({});
    setAskUserRequest(null);
  }, []);

  const executePlan = useCallback((onDone?: () => void) => {
    setPlanReady(false);
    api.setConversationMode("normal").then(() => {
      setConversationMode("normal");
      sendMessageRef.current("请按照计划逐步执行，开始吧。", onDone);
    });
  }, []);

  const discardPlan = useCallback(async () => {
    setPlanReady(false);
    setPlanSlug(null);
    try {
      await api.discardPlan();
      setConversationMode("normal");
    } catch {
      await api.setConversationMode("normal");
      setConversationMode("normal");
    }
  }, []);

  const refinePlan = useCallback(() => {
    setPlanReady(false);
  }, []);

  const togglePlanMode = useCallback(async () => {
    const next = conversationMode === "plan" ? "normal" : "plan";
    const res = await api.setConversationMode(next);
    setConversationMode(res.mode as "normal" | "plan");
    setPlanReady(false);
    setPlanSuggestion(null);
  }, [conversationMode]);

  const acceptPlanSuggestion = useCallback(async () => {
    setPlanSuggestion(null);
    const res = await api.setConversationMode("plan");
    setConversationMode(res.mode as "normal" | "plan");
  }, []);

  const dismissPlanSuggestion = useCallback(() => {
    setPlanSuggestion(null);
  }, []);

  const cancelChat = useCallback(() => {
    abortRef.current?.abort();
    setBusy(false);
    fetch(`${api.getBaseUrl()}/api/chat/stop`, { method: "POST" }).catch(() => {});
  }, []);

  return {
    displayMessages,
    setDisplayMessages: resetMessages,
    busy,
    sendMessage,
    cancelChat,
    permissionRequest,
    respondPermission,
    askUserRequest,
    respondAskUser,
    skipAskUser,
    conversationMode,
    planReady,
    setPlanReady,
    executePlan,
    discardPlan,
    refinePlan,
    togglePlanMode,
    planSuggestion,
    acceptPlanSuggestion,
    dismissPlanSuggestion,
    todos,
    planSlug,
    setPlanSlug,
  };
}

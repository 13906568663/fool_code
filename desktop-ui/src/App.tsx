import { useState, useEffect, useCallback, useRef } from "react";
import { ChevronDown, Menu } from "lucide-react";
import { setBaseUrl } from "./services/api";
import * as api from "./services/api";
import { useSessions } from "./hooks/useSessions";
import { useChat } from "./hooks/useChat";
import type { Artifact, ChatMessage, DisplayMessage, DisplayBlock } from "./types";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import InputArea from "./components/InputArea";
import SettingsPanel from "./components/SettingsPanel";
import SkillStorePage from "./components/SkillStorePage";
import PermissionDialog from "./components/PermissionDialog";
import AskUserDialog from "./components/AskUserDialog";
import ArtifactPanel from "./components/ArtifactPanel";
import { getBaseUrl } from "./services/api";

function extractImagesFromBlocks(
  blocks?: DisplayBlock[],
): { url: string; alt: string }[] {
  if (!blocks) return [];
  const base = getBaseUrl();
  const images: { url: string; alt: string }[] = [];

  for (const b of blocks) {
    if (b.type !== "image_ref" || !b.meta?.path) continue;
    const raw = String(b.meta.path).replace(/\\/g, "/");
    const parts = raw.split("/");
    const filename = parts[parts.length - 1];
    const cacheIdx = parts.indexOf("image-cache");
    const sessionId =
      cacheIdx >= 0 && cacheIdx + 1 < parts.length - 1
        ? parts[cacheIdx + 1]
        : null;
    if (sessionId && filename) {
      images.push({
        url: `${base}/api/images/${sessionId}/${filename}`,
        alt: String(b.content ?? "image"),
      });
    }
  }
  return images;
}

function extractFilesFromBlocks(
  blocks?: DisplayBlock[],
): { filename: string; category: string; size: number; fileId: string; markdownPath?: string; cachedPath?: string }[] {
  if (!blocks) return [];
  const files: { filename: string; category: string; size: number; fileId: string; markdownPath?: string; cachedPath?: string }[] = [];

  for (const b of blocks) {
    if (b.type !== "document_ref" || !b.meta) continue;
    const mdPath = b.meta.markdown_path ? String(b.meta.markdown_path) : undefined;
    const cachedRaw = b.meta.cached_path ? String(b.meta.cached_path) : undefined;
    const cachedPath = cachedRaw || (mdPath && mdPath.endsWith(".md") ? mdPath.slice(0, -3) : undefined);
    files.push({
      filename: String(b.meta.filename ?? b.content ?? "file"),
      category: String(b.meta.category ?? "document"),
      size: Number(b.meta.size ?? 0),
      fileId: String(b.meta.file_id ?? ""),
      markdownPath: mdPath,
      cachedPath,
    });
  }
  return files;
}

function chatMessagesToDisplay(messages: ChatMessage[]): DisplayMessage[] {
  interface Turn {
    role: "user" | "assistant";
    messages: ChatMessage[];
    is_plan?: boolean;
  }
  const turns: Turn[] = [];
  for (const msg of messages) {
    const prev = turns[turns.length - 1];
    if (msg.role === "assistant" && prev?.role === "assistant") {
      prev.messages.push(msg);
      if (msg.is_plan) prev.is_plan = true;
    } else {
      turns.push({
        role: msg.role as "user" | "assistant",
        messages: [msg],
        is_plan: msg.is_plan,
      });
    }
  }

  return turns.map((turn, index) => {
    let fullContent = "";
    const allToolBlocks: import("./types").ToolBlock[] = [];
    const steps: import("./types").MessageStep[] = [];
    const allBlocks: DisplayBlock[] = [];

    const allResults: DisplayBlock[] = [];
    for (const msg of turn.messages) {
      for (const b of msg.blocks || []) {
        if (b.type === "tool_result") allResults.push(b);
      }
    }
    const results = [...allResults];

    for (const msg of turn.messages) {
      allBlocks.push(...(msg.blocks || []));

      if (msg.content) {
        if (fullContent) fullContent += "\n\n";
        fullContent += msg.content;

        const lastStep = steps[steps.length - 1];
        if (lastStep && lastStep.type === "text") {
          steps[steps.length - 1] = {
            ...lastStep,
            content: lastStep.content + "\n\n" + msg.content,
          };
        } else {
          steps.push({ type: "text", content: msg.content });
        }
      }

      const calls = (msg.blocks || []).filter((b) => b.type === "tool_call");
      if (calls.length > 0) {
        const groupBlocks: import("./types").ToolBlock[] = [];
        for (const tc of calls) {
          const name = tc.content || "unknown";
          const toolUseId = (tc.meta?.id as string) || "";
          const input = (tc.meta?.input as string) || "";

          let matchingResult: DisplayBlock | undefined;
          const byId = results.findIndex(
            (tr) => tr.meta?.tool_use_id === toolUseId,
          );
          if (byId >= 0) {
            matchingResult = results.splice(byId, 1)[0];
          } else {
            const byName = results.findIndex(
              (tr) => tr.meta?.tool_name === name,
            );
            if (byName >= 0) {
              matchingResult = results.splice(byName, 1)[0];
            }
          }

          const block: import("./types").ToolBlock = {
            type: "tool_end",
            name,
            input,
            output: matchingResult?.content || undefined,
            error: Boolean(matchingResult?.meta?.is_error),
            status: matchingResult
              ? matchingResult.meta?.is_error
                ? "error"
                : "success"
              : "success",
          };
          groupBlocks.push(block);
          allToolBlocks.push(block);
        }

        const lastStep = steps[steps.length - 1];
        if (lastStep && lastStep.type === "tool_group") {
          steps[steps.length - 1] = {
            ...lastStep,
            blocks: [...lastStep.blocks, ...groupBlocks],
          };
        } else {
          steps.push({ type: "tool_group", blocks: groupBlocks });
        }
      }
    }

    return {
      id: `hist-${index}`,
      role: turn.role,
      content: fullContent,
      toolBlocks: allToolBlocks,
      steps,
      isPlan: turn.is_plan,
      images: extractImagesFromBlocks(allBlocks),
      files: extractFilesFromBlocks(allBlocks),
    };
  });
}

export default function App() {
  const [ready, setReady] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [skillStoreOpen, setSkillStoreOpen] = useState(false);
  const [modelName, setModelName] = useState("加载中...");
  const [configured, setConfigured] = useState(true);
  const [activeArtifact, setActiveArtifact] = useState<Artifact | null>(null);
  const [artifactVisible, setArtifactVisible] = useState(false);
  const artifactTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const {
    sessions,
    activeId,
    messages: sessionMessages,
    title,
    loading: sessionsLoading,
    createSession,
    switchSession,
    removeSession,
    loadSessions,
    loadSessionMessages,
    sessionModel,
    planStatus,
    planTodos: sessionPlanTodos,
    sessionPlanSlug,
    updateSessionModelLocal,
  } = useSessions();

  const {
    displayMessages,
    setDisplayMessages,
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
  } = useChat();

  useEffect(() => {
    setBaseUrl(window.location.origin);
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    api
      .getStatus()
      .then((status) => {
        setModelName(status.model);
        setConfigured(status.configured);
      })
      .catch(() => {
        setModelName("连接失败");
      });
  }, [ready]);

  useEffect(() => {
    if (!settingsOpen && activeId) {
      loadSessionMessages(activeId);
    }
  }, [settingsOpen, activeId, loadSessionMessages]);

  useEffect(() => {
    if (!busy) {
      setDisplayMessages(chatMessagesToDisplay(sessionMessages), sessionPlanTodos);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionMessages, setDisplayMessages, sessionPlanTodos]);

  useEffect(() => {
    if (sessionPlanSlug) {
      setPlanSlug(sessionPlanSlug);
    }
  }, [sessionPlanSlug, setPlanSlug]);

  useEffect(() => {
    if (planStatus === "drafted") {
      setPlanReady(true);
    } else {
      setPlanReady(false);
    }
  }, [planStatus, setPlanReady]);

  const handleSend = useCallback(
    (text: string) => {
      sendMessage(text, () => {
        loadSessions();
        if (activeId) {
          loadSessionMessages(activeId);
        }
      });
    },
    [sendMessage, loadSessions, loadSessionMessages, activeId]
  );

  const handleExecutePlan = useCallback(() => {
    executePlan(() => {
      loadSessions();
      if (activeId) {
        loadSessionMessages(activeId);
      }
    });
  }, [executePlan, loadSessions, loadSessionMessages, activeId]);

  const handleNewChat = useCallback(async () => {
    if (busy) return;
    await createSession();
    setDisplayMessages([]);
  }, [busy, createSession, setDisplayMessages]);

  const handleSwitch = useCallback(
    async (id: string) => {
      if (busy) return;
      await switchSession(id);
    },
    [busy, switchSession]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      if (busy) return;
      await removeSession(id);
    },
    [busy, removeSession]
  );

  const openArtifact = useCallback((artifact: Artifact) => {
    if (artifactTimerRef.current) clearTimeout(artifactTimerRef.current);
    setActiveArtifact(artifact);
    requestAnimationFrame(() => setArtifactVisible(true));
  }, []);

  const closeArtifact = useCallback(() => {
    setArtifactVisible(false);
    artifactTimerRef.current = setTimeout(() => setActiveArtifact(null), 300);
  }, []);

  const providerSelectOptions = useCallback(() => {
    const rows: { value: string; label: string }[] = [
      { value: "__default__", label: "工作区默认提供商" },
    ];
    for (const provider of sessionModel.providers) {
      rows.push({
        value: provider.id,
        label: provider.label || provider.id,
      });
    }
    return rows;
  }, [sessionModel]);

  const modelSelectOptions = useCallback(() => {
    const rows: { value: string; label: string }[] = [
      {
        value: "__default__",
        label: `默认 (${sessionModel.defaultModel || "工作区"})`,
      },
    ];
    const seen = new Set<string>();
    for (const id of sessionModel.savedModels) {
      if (!id || seen.has(id)) continue;
      seen.add(id);
      rows.push({ value: id, label: id });
    }
    if (sessionModel.chatModel && !seen.has(sessionModel.chatModel)) {
      rows.push({ value: sessionModel.chatModel, label: sessionModel.chatModel });
    }
    return rows;
  }, [sessionModel]);

  const handleSessionProviderChange = useCallback(
    async (event: React.ChangeEvent<HTMLSelectElement>) => {
      if (!activeId || busy) return;
      const value = event.target.value;
      const providerId = value === "__default__" ? "" : value;
      try {
        await api.setSessionProvider(activeId, providerId);
        await loadSessionMessages(activeId);
      } catch {
        // ignore selector update errors for now
      }
    },
    [activeId, busy, loadSessionMessages]
  );

  const handleSessionModelChange = useCallback(
    async (event: React.ChangeEvent<HTMLSelectElement>) => {
      if (!activeId || busy) return;
      const value = event.target.value;
      const model = value === "__default__" ? "" : value;
      try {
        const result = await api.setSessionModel(activeId, model);
        updateSessionModelLocal(result.effective_model, result.chat_model);
      } catch {
        // ignore selector update errors for now
      }
    },
    [activeId, busy, updateSessionModelLocal]
  );

  if (!ready || sessionsLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-[linear-gradient(180deg,#F9FBFF,#F5F7FB)] px-6">
        <div className="text-center">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-[#DCE7FF] border-t-[#4C84FF]" />
          <p className="mt-4 text-sm text-slate-500">正在启动 Fool Code...</p>
        </div>
      </div>
    );
  }

  const selectClassName =
    "h-10 appearance-none rounded-full border border-[#E7ECF3] bg-[#FCFDFF] pl-4 pr-9 text-sm text-slate-700 outline-none transition hover:border-[#DCE7FF] focus:border-[#D7E4FF] focus:bg-white focus:ring-4 focus:ring-[#EEF4FF] disabled:cursor-not-allowed disabled:opacity-50";

  return (
    <div className="h-screen overflow-hidden bg-[linear-gradient(180deg,#F9FBFF,#F5F7FB)] p-3 text-slate-900 md:p-4">
      <div className="mx-auto flex h-full max-w-[1700px] gap-3">
        <aside className="hidden shrink-0 md:block">
          <Sidebar
            sessions={sessions}
            activeId={activeId}
            collapsed={sidebarCollapsed}
            busy={busy}
            onNewChat={handleNewChat}
            onSwitch={handleSwitch}
            onDelete={handleDelete}
            onOpenSettings={() => setSettingsOpen(true)}
            onOpenSkillStore={() => setSkillStoreOpen(true)}
          />
        </aside>

        <section className="relative flex min-w-0 flex-1 flex-col overflow-hidden rounded-[32px] border border-[#E7ECF3] bg-white shadow-[0_18px_52px_rgba(31,42,68,0.06)]">
          <header className="border-b border-[#EEF2F7] bg-white/95 px-5 py-3 sm:px-6">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <button
                  type="button"
                  onClick={() => setSidebarCollapsed((value) => !value)}
                  className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-[#E7ECF3] bg-[#FCFDFF] text-slate-500 transition hover:border-[#DCE7FF] hover:bg-white hover:text-slate-700"
                  title={sidebarCollapsed ? "展开会话列表" : "收起会话列表"}
                >
                  <Menu size={18} />
                </button>

                <div className="min-w-0">
                  <div className="truncate text-[20px] font-semibold tracking-tight text-slate-800">
                    {title || "新对话"}
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#35C58A]" />
                    <span>
                      {configured
                        ? "当前会话已就绪，可以继续提问、执行工具或拖入文件。"
                        : "还没有完成模型配置，先去设置里补齐提供商和 API Key。"}
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-end gap-2">
                {configured ? (
                  <>
                    {sessionModel.providers.length > 1 && (
                      <label className="relative block">
                        <span className="sr-only">提供商</span>
                        <select
                          value={
                            sessionModel.chatProviderId == null ||
                            sessionModel.chatProviderId === ""
                              ? "__default__"
                              : sessionModel.chatProviderId
                          }
                          onChange={handleSessionProviderChange}
                          disabled={busy}
                          className={`${selectClassName} min-w-[170px] max-w-[220px]`}
                          title="本对话使用的模型提供商"
                        >
                          {providerSelectOptions().map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                        <ChevronDown
                          size={14}
                          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-400"
                        />
                      </label>
                    )}

                    <label className="relative block">
                      <span className="sr-only">本对话模型</span>
                      <select
                        value={
                          sessionModel.chatModel == null || sessionModel.chatModel === ""
                            ? "__default__"
                            : sessionModel.chatModel
                        }
                        onChange={handleSessionModelChange}
                        disabled={busy}
                        className={`${selectClassName} min-w-[180px] max-w-[280px]`}
                        title={sessionModel.effectiveModel}
                      >
                        {modelSelectOptions().map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <ChevronDown
                        size={14}
                        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-400"
                      />
                    </label>

                    <span className="inline-flex h-10 items-center gap-2 rounded-full border border-[#E7ECF3] bg-[#FCFDFF] px-4 text-sm text-slate-600">
                      <span className="inline-block h-2 w-2 rounded-full bg-[#35C58A]" />
                      就绪
                    </span>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => setSettingsOpen(true)}
                    className="inline-flex h-10 items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-4 text-sm font-medium text-amber-700 transition hover:bg-amber-100"
                    title={`当前状态：${modelName}`}
                  >
                    <span className="inline-block h-2 w-2 rounded-full bg-amber-500" />
                    未配置 · 点击设置
                  </button>
                )}
              </div>
            </div>
          </header>

          <div className="relative flex min-h-0 flex-1 overflow-hidden bg-white">
            <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
              <ChatView
                messages={displayMessages}
                configured={configured}
                onOpenSettings={() => setSettingsOpen(true)}
                onOpenArtifact={openArtifact}
                todos={todos}
                planStatus={planStatus}
                planReady={planReady}
                planSlug={planSlug}
                onExecutePlan={handleExecutePlan}
                onDiscardPlan={discardPlan}
                onRefinePlan={refinePlan}
              />

              <InputArea
                busy={busy}
                sessionId={activeId}
                onSend={handleSend}
                onCancel={cancelChat}
                conversationMode={conversationMode}
                planReady={planReady}
                onTogglePlanMode={togglePlanMode}
                planSuggestion={planSuggestion}
                onAcceptPlanSuggestion={acceptPlanSuggestion}
                onDismissPlanSuggestion={dismissPlanSuggestion}
              />
            </div>

            <ArtifactPanel
              artifact={activeArtifact}
              visible={artifactVisible}
              onClose={closeArtifact}
            />
          </div>
        </section>
      </div>

      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onModelChange={setModelName}
      />

      <SkillStorePage
        open={skillStoreOpen}
        onClose={() => setSkillStoreOpen(false)}
      />

      {permissionRequest && (
        <PermissionDialog
          toolName={permissionRequest.toolName}
          input={permissionRequest.input}
          onDecision={respondPermission}
        />
      )}

      {askUserRequest && (
        <AskUserDialog
          questions={askUserRequest.questions}
          onSubmit={respondAskUser}
          onSkip={skipAskUser}
        />
      )}
    </div>
  );
}

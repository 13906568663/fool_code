import { useState, useCallback, useEffect } from "react";
import type { SessionListItem, ChatMessage, ProviderSummary, TodoItem } from "../types";
import * as api from "../services/api";

export interface SessionModelState {
  effectiveModel: string;
  chatModel: string | null;
  chatProviderId: string | null;
  defaultProviderId: string;
  providers: ProviderSummary[];
  defaultModel: string;
  savedModels: string[];
}

export function useSessions() {
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [activeId, setActiveId] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [title, setTitle] = useState("新对话");
  const [loading, setLoading] = useState(true);
  const [planStatus, setPlanStatus] = useState<string>("none");
  const [planTodos, setPlanTodos] = useState<TodoItem[]>([]);
  const [sessionPlanSlug, setSessionPlanSlug] = useState<string | null>(null);
  const [sessionModel, setSessionModel] = useState<SessionModelState>({
    effectiveModel: "",
    chatModel: null,
    chatProviderId: null,
    defaultProviderId: "",
    providers: [],
    defaultModel: "",
    savedModels: [],
  });

  const loadSessions = useCallback(async () => {
    try {
      const data = await api.getSessions();
      setSessions(data.sessions);
      setActiveId(data.active_id);
      return data;
    } catch {
      // silently fail
    }
  }, []);

  const loadSessionMessages = useCallback(async (id: string) => {
    try {
      const detail = await api.getSession(id);
      setTitle(detail.title);
      setMessages(detail.messages);
      setPlanStatus(detail.plan_status ?? "none");
      setSessionPlanSlug(detail.plan_slug ?? null);
      setPlanTodos((detail.plan_todos ?? []).map((t) => ({
        id: (t as { id?: string }).id,
        content: t.content,
        activeForm: "",
        status: t.status,
      })));
      const def = detail.default_model ?? "";
      const saved = detail.saved_models ?? [];
      setSessionModel({
        effectiveModel: detail.effective_model ?? def,
        chatModel: detail.chat_model ?? null,
        chatProviderId: detail.chat_provider_id ?? null,
        defaultProviderId: detail.default_provider_id ?? "",
        providers: detail.providers ?? [],
        defaultModel: def,
        savedModels: saved,
      });
    } catch {
      // silently fail
    }
  }, []);

  const createSession = useCallback(async () => {
    const data = await api.createSession();
    setSessions(data.sessions);
    setActiveId(data.active_id);
    setMessages([]);
    setTitle("新对话");
    setPlanStatus("none");
    setPlanTodos([]);
    setSessionPlanSlug(null);
    await loadSessionMessages(data.active_id);
    return data;
  }, [loadSessionMessages]);

  const switchSession = useCallback(
    async (id: string) => {
      if (id === activeId) return;
      const data = await api.switchSession(id);
      setSessions(data.sessions);
      setActiveId(data.active_id);
      await loadSessionMessages(id);
      return data;
    },
    [activeId, loadSessionMessages]
  );

  const removeSession = useCallback(
    async (id: string) => {
      const data = await api.deleteSession(id);
      const switched = data.active_id !== activeId;
      setSessions(data.sessions);
      setActiveId(data.active_id);
      if (switched) {
        await loadSessionMessages(data.active_id);
      }
      return data;
    },
    [activeId, loadSessionMessages]
  );

  useEffect(() => {
    (async () => {
      setLoading(true);
      const data = await loadSessions();
      if (data?.active_id) {
        await loadSessionMessages(data.active_id);
      }
      setLoading(false);
    })();
  }, [loadSessions, loadSessionMessages]);

  const updateSessionModelLocal = useCallback(
    (effective: string, chat: string | null) => {
      setSessionModel((prev) => ({
        ...prev,
        effectiveModel: effective,
        chatModel: chat,
      }));
    },
    []
  );

  return {
    sessions,
    activeId,
    messages,
    setMessages,
    title,
    setTitle,
    loading,
    sessionModel,
    planStatus,
    planTodos,
    sessionPlanSlug,
    updateSessionModelLocal,
    createSession,
    switchSession,
    removeSession,
    loadSessions,
    loadSessionMessages,
  };
}

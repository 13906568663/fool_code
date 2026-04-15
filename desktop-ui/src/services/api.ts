import type {
  PermissionMode,
  PermissionModeResponse,
  StatusResponse,
  SessionsResponse,
  SessionDetailResponse,
  SettingsResponse,
  SaveSettingsRequest,
  ModelsResponse,
  DiscoverModelsRequest,
  SkillsResponse,
  BuiltinBrowserMcpResponse,
  McpServersResponse,
  SaveMcpServerRequest,
  SaveBuiltinBrowserMcpRequest,
  ConnectMcpServerResponse,
  WorkspaceResponse,
  WebEvent,
  MarketSearchResponse,
  MarketInstallResponse,
} from "../types";

let BASE_URL = "";

export function setBaseUrl(url: string) {
  BASE_URL = url.replace(/\/$/, "");
}

export function getBaseUrl(): string {
  return BASE_URL;
}

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  return response.json();
}

export async function getStatus(): Promise<StatusResponse> {
  return request("/api/status");
}

export async function getSessions(): Promise<SessionsResponse> {
  return request("/api/sessions");
}

export async function createSession(): Promise<SessionsResponse> {
  return request("/api/sessions/new", { method: "POST" });
}

export async function getSession(id: string): Promise<SessionDetailResponse> {
  return request(`/api/sessions/${id}`);
}

export async function switchSession(id: string): Promise<SessionsResponse> {
  return request(`/api/sessions/${id}/switch`, { method: "POST" });
}

export async function deleteSession(id: string): Promise<SessionsResponse> {
  return request(`/api/sessions/${id}`, { method: "DELETE" });
}

export async function getSettings(): Promise<SettingsResponse> {
  return request("/api/settings");
}

export async function saveSettings(
  settings: SaveSettingsRequest
): Promise<SettingsResponse> {
  return request("/api/settings", {
    method: "POST",
    body: JSON.stringify(settings),
  });
}

export async function getModels(provider: string): Promise<ModelsResponse> {
  return request(`/api/models?provider=${encodeURIComponent(provider)}`);
}

export async function discoverModels(
  body: DiscoverModelsRequest
): Promise<ModelsResponse> {
  return request("/api/models/discover", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function setSessionModel(
  sessionId: string,
  model: string
): Promise<{
  ok: boolean;
  effective_model: string;
  chat_model: string | null;
}> {
  return request(`/api/sessions/${sessionId}/model`, {
    method: "POST",
    body: JSON.stringify({ model }),
  });
}

export async function setSessionProvider(
  sessionId: string,
  providerId: string
): Promise<{
  ok: boolean;
  effective_model: string;
  chat_provider_id: string | null;
}> {
  return request(`/api/sessions/${sessionId}/provider`, {
    method: "POST",
    body: JSON.stringify({ provider_id: providerId }),
  });
}

export async function getSkills(): Promise<SkillsResponse> {
  return request("/api/skills");
}

export async function getMcpServers(): Promise<McpServersResponse> {
  return request("/api/mcp-servers");
}

export async function getBuiltinBrowserMcp(): Promise<BuiltinBrowserMcpResponse> {
  return request("/api/internal-mcp/browser");
}

export async function saveBuiltinBrowserMcp(
  body: SaveBuiltinBrowserMcpRequest
): Promise<BuiltinBrowserMcpResponse> {
  return request("/api/internal-mcp/browser", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function reconnectBuiltinBrowserMcp(): Promise<BuiltinBrowserMcpResponse> {
  return request("/api/internal-mcp/browser/reconnect", {
    method: "POST",
  });
}

export async function saveMcpServer(
  server: SaveMcpServerRequest
): Promise<McpServersResponse> {
  return request("/api/mcp-servers/save", {
    method: "POST",
    body: JSON.stringify(server),
  });
}

export async function deleteMcpServer(
  name: string
): Promise<McpServersResponse> {
  return request("/api/mcp-servers/delete", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function connectMcpServer(
  name: string
): Promise<ConnectMcpServerResponse> {
  return request("/api/mcp-servers/connect", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function toggleMcpServer(
  name: string,
  enabled: boolean
): Promise<McpServersResponse> {
  return request("/api/mcp-servers/toggle", {
    method: "POST",
    body: JSON.stringify({ name, enabled }),
  });
}

export async function disconnectMcpServer(
  name: string
): Promise<McpServersResponse> {
  return request("/api/mcp-servers/disconnect", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function getWorkspace(): Promise<WorkspaceResponse> {
  return request("/api/workspace");
}

export async function setWorkspace(
  workspace_root: string
): Promise<WorkspaceResponse> {
  return request("/api/workspace", {
    method: "POST",
    body: JSON.stringify({ workspace_root }),
  });
}

export async function sendPermissionDecision(
  decision: string
): Promise<void> {
  await request("/api/permission", {
    method: "POST",
    body: JSON.stringify({ decision }),
  });
}

export async function sendAskUserAnswer(
  answers: Record<string, string>
): Promise<void> {
  await request("/api/ask-user-answer", {
    method: "POST",
    body: JSON.stringify({ answers }),
  });
}

export async function getPermissionMode(): Promise<PermissionModeResponse> {
  return request("/api/permission-mode");
}

export async function setPermissionMode(
  mode: PermissionMode
): Promise<PermissionModeResponse> {
  return request("/api/permission-mode", {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

// Conversation mode (plan / normal)

export async function getConversationMode(): Promise<{ mode: string }> {
  return request("/api/conversation-mode");
}

export async function setConversationMode(
  mode: "normal" | "plan"
): Promise<{ mode: string }> {
  return request("/api/conversation-mode", {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

// Memory

export async function getMemoryList(): Promise<
  import("../types").MemoryListResponse
> {
  return request("/api/memory");
}

export async function getMemory(
  memoryType: string
): Promise<import("../types").MemoryContentResponse> {
  return request(`/api/memory/${memoryType}`);
}

export async function saveMemory(
  memoryType: string,
  content: string
): Promise<{ ok: boolean; type: string }> {
  return request(`/api/memory/${memoryType}`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export async function toggleMemory(
  enabled: boolean
): Promise<{ ok: boolean; enabled: boolean }> {
  return request("/api/memory/toggle", {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
}

// Model roles

export async function getModelRoles(): Promise<
  import("../types").ModelRolesResponse
> {
  return request("/api/model-roles");
}

export async function saveModelRoles(
  roles: Partial<{
    verification: import("../types").ModelRoleConfig;
    memory: import("../types").ModelRoleConfig;
  }>
): Promise<{ ok: boolean }> {
  return request("/api/model-roles", {
    method: "POST",
    body: JSON.stringify(roles),
  });
}

// Playbooks

export async function getPlaybooks(): Promise<
  import("../types").PlaybooksResponse
> {
  return request("/api/playbooks");
}

export async function getPlaybook(
  category: string,
  filename: string
): Promise<import("../types").PlaybookContentResponse> {
  return request(
    `/api/playbooks/${encodeURIComponent(category)}/${encodeURIComponent(filename)}`
  );
}

export async function savePlaybook(
  category: string,
  filename: string,
  content: string
): Promise<{ ok: boolean; path: string }> {
  return request(
    `/api/playbooks/${encodeURIComponent(category)}/${encodeURIComponent(filename)}`,
    { method: "POST", body: JSON.stringify({ content }) }
  );
}

export async function deletePlaybook(
  category: string,
  filename: string
): Promise<{ ok: boolean }> {
  return request(
    `/api/playbooks/${encodeURIComponent(category)}/${encodeURIComponent(filename)}`,
    { method: "DELETE" }
  );
}

export async function createPlaybookCategory(
  name: string,
  description: string
): Promise<{ ok: boolean; path: string }> {
  return request("/api/playbooks/category", {
    method: "POST",
    body: JSON.stringify({ name, description }),
  });
}

export async function deletePlaybookCategory(
  name: string
): Promise<{ ok: boolean }> {
  return request(`/api/playbooks/category/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export async function getPlaybookTemplate(): Promise<{ template: string }> {
  return request("/api/playbooks/template");
}

export async function fetchPlanContent(
  slug: string,
): Promise<{ slug: string; content: string; todos?: { id: string; content: string; status: string }[]; status?: string }> {
  return request(`/api/plans/${encodeURIComponent(slug)}`);
}

export async function discardPlan(): Promise<{ ok: boolean }> {
  return request("/api/plan/discard", { method: "POST" });
}

export function streamChat(
  message: string,
  onEvent: (event: WebEvent) => void,
  onError: (error: Error) => void,
  onDone: () => void
): AbortController {
  const controller = new AbortController();

  fetch(`${BASE_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    signal: controller.signal,
  })
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      function read() {
        reader
          .read()
          .then(({ done, value }) => {
            if (done) {
              onDone();
              return;
            }
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              const data = line.slice(6);
              if (data === "[DONE]") continue;
              try {
                const evt: WebEvent = JSON.parse(data);
                onEvent(evt);
                if (evt.type === "done") {
                  onDone();
                  return;
                }
              } catch {
                // ignore parse errors
              }
            }
            read();
          })
          .catch((err) => {
            if (err.name !== "AbortError") {
              onError(err);
            }
          });
      }
      read();
    })
    .catch((err) => {
      if (err.name !== "AbortError") {
        onError(err);
      }
    });

  return controller;
}

// ----- Buddy AI chat -----

export async function buddyChat(
  prompt: string,
  name: string = "小猫",
): Promise<string> {
  try {
    const res = await request<{ text: string }>("/api/buddy/chat", {
      method: "POST",
      body: JSON.stringify({ prompt, name }),
    });
    return res.text || "";
  } catch {
    return "";
  }
}

// ----- File processing -----

export interface FileProcessResult {
  file_id: string;
  filename: string;
  category: string;
  size: number;
  preview: string;
  cached_path: string;
  markdown_path: string;
  meta: Record<string, unknown>;
  error?: string;
}

export async function processFile(
  path: string,
  sessionId: string,
): Promise<FileProcessResult> {
  const res = await fetch(`${BASE_URL}/api/file-process`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, session_id: sessionId }),
  });
  return res.json();
}

export async function fetchFileContent(
  markdownPath: string,
): Promise<{ content: string; path: string }> {
  const res = await fetch(
    `${BASE_URL}/api/file-content?path=${encodeURIComponent(markdownPath)}`,
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export function getFileCacheUrl(cachedPath: string): string {
  const normalized = cachedPath.replace(/\\/g, "/");
  const cacheIdx = normalized.indexOf("/file-cache/");
  if (cacheIdx < 0) return `${BASE_URL}/api/file-preview?path=${encodeURIComponent(cachedPath)}`;
  const relative = normalized.slice(cacheIdx + "/file-cache/".length);
  return `${BASE_URL}/api/file-cache/${relative}`;
}

// ─── Skill Store API ───

import type {
  SkillStoreListResponse,
  SkillStoreDetailResponse,
  SkillStoreImportResponse,
  SkillStoreStatsResponse,
  SkillRelationsResponse,
} from "../types";

export async function getSkillStoreStats(): Promise<SkillStoreStatsResponse> {
  return request("/api/skill-store/stats");
}

export async function listSkillStoreSkills(params?: {
  category?: string;
  enabled?: boolean;
  pinned?: boolean;
}): Promise<SkillStoreListResponse> {
  const qs = new URLSearchParams();
  if (params?.category) qs.set("category", params.category);
  if (params?.enabled !== undefined) qs.set("enabled", String(params.enabled));
  if (params?.pinned !== undefined) qs.set("pinned", String(params.pinned));
  const q = qs.toString();
  return request(`/api/skill-store/list${q ? "?" + q : ""}`);
}

export async function searchSkillStoreSkills(
  query: string,
  limit: number = 20,
): Promise<SkillStoreListResponse> {
  const qs = new URLSearchParams({ q: query, limit: String(limit) });
  return request(`/api/skill-store/search?${qs}`);
}

export async function getSkillStoreDetail(
  skillId: string,
): Promise<SkillStoreDetailResponse> {
  return request(`/api/skill-store/${encodeURIComponent(skillId)}`);
}

export async function importSkills(
  scanRoot: string,
): Promise<SkillStoreImportResponse> {
  return request("/api/skill-store/import", {
    method: "POST",
    body: JSON.stringify({ scan_root: scanRoot }),
  });
}

export async function updateSkill(
  skillId: string,
  data: {
    display_name?: string;
    description?: string;
    category?: string;
    trigger_terms?: string[];
  },
): Promise<{ ok: boolean }> {
  return request(`/api/skill-store/${encodeURIComponent(skillId)}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteSkillStore(
  skillId: string,
): Promise<{ ok: boolean }> {
  return request(`/api/skill-store/${encodeURIComponent(skillId)}`, {
    method: "DELETE",
  });
}

export async function toggleSkillEnabled(
  skillId: string,
  enabled: boolean,
): Promise<{ ok: boolean; enabled: boolean }> {
  return request(`/api/skill-store/${encodeURIComponent(skillId)}/toggle`, {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
}

export async function toggleSkillPinned(
  skillId: string,
  pinned: boolean,
): Promise<{ ok: boolean; pinned: boolean }> {
  return request(`/api/skill-store/${encodeURIComponent(skillId)}/pin`, {
    method: "POST",
    body: JSON.stringify({ pinned }),
  });
}

export interface IngestProgressEvent {
  type: "progress";
  current: number;
  total: number;
  skill: string;
  status: string;
}

export interface IngestDoneEvent {
  type: "done";
  summary: string;
  added: number;
  updated: number;
  errors: number;
  total_scanned: number;
}

export interface IngestErrorEvent {
  type: "error";
  message: string;
}

export type IngestEvent = IngestProgressEvent | IngestDoneEvent | IngestErrorEvent;

async function streamIngest(
  url: string,
  onEvent: (evt: IngestEvent) => void,
): Promise<void> {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const reader = resp.body?.getReader();
  if (!reader) throw new Error("No response body");
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      try {
        const evt = JSON.parse(trimmed.slice(5).trim()) as IngestEvent;
        onEvent(evt);
      } catch { /* skip malformed */ }
    }
  }
}

export async function rescanSkillStore(
  onEvent: (evt: IngestEvent) => void,
): Promise<void> {
  return streamIngest("/api/skill-store/rescan", onEvent);
}

export async function reindexSkillStore(
  onEvent: (evt: IngestEvent) => void,
): Promise<void> {
  return streamIngest("/api/skill-store/reindex", onEvent);
}

export async function recordSkillFeedback(
  skillId: string,
  helpful: boolean,
  sessionId?: string,
): Promise<{ ok: boolean }> {
  return request(`/api/skill-store/${encodeURIComponent(skillId)}/feedback`, {
    method: "POST",
    body: JSON.stringify({ helpful, session_id: sessionId || "" }),
  });
}

export async function getSkillRelations(
  skillId?: string,
): Promise<SkillRelationsResponse> {
  const path = skillId
    ? `/api/skill-store/relations/${encodeURIComponent(skillId)}`
    : "/api/skill-store/relations";
  return request(path);
}

// ─── Skill Market (ClawHub) ───

export async function searchSkillMarket(
  query: string,
  limit: number = 20,
): Promise<MarketSearchResponse> {
  const qs = new URLSearchParams({ q: query, limit: String(limit) });
  return request(`/api/skill-market/search?${qs}`);
}

export async function getPopularSkills(
  limit: number = 20,
): Promise<MarketSearchResponse> {
  return request(`/api/skill-market/popular?limit=${limit}`);
}

export async function installSkillFromMarket(
  slug: string,
): Promise<MarketInstallResponse> {
  return request("/api/skill-market/install", {
    method: "POST",
    body: JSON.stringify({ slug }),
  });
}

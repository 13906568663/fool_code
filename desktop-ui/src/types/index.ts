export interface StatusResponse {
  model: string;
  status: string;
  active_session: string;
  configured: boolean;
}

export type PermissionMode =
  | "default"
  | "danger-full-access"
  | "read-only"
  | "workspace-write"
  | "dont-ask";

export interface PermissionModeResponse {
  mode: PermissionMode;
}

export interface WorkspaceResponse {
  workspace_root: string;
  app_data_root: string;
  config_path: string;
  sessions_path: string;
  skills_path: string;
}

export interface SessionListItem {
  id: string;
  title: string;
  created_at: number;
  message_count: number;
  active: boolean;
}

export interface SessionsResponse {
  sessions: SessionListItem[];
  active_id: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  is_plan?: boolean;
  blocks?: DisplayBlock[];
}

export interface DisplayBlock {
  type: string;
  content?: string;
  meta?: Record<string, unknown>;
}

export interface ProviderSummary {
  id: string;
  label: string;
}

export interface SessionDetailResponse {
  id: string;
  title: string;
  messages: ChatMessage[];
  chat_model?: string | null;
  chat_provider_id?: string | null;
  default_provider_id?: string;
  providers?: ProviderSummary[];
  default_model?: string;
  saved_models?: string[];
  effective_model?: string;
  plan_status?: string;
  plan_slug?: string | null;
  plan_todos?: TodoItem[];
}

export interface ModelProviderRow {
  id: string;
  label: string;
  provider: string;
  api_key_masked: string;
  base_url: string;
  model: string;
  saved_models: string[];
}

export interface SettingsResponse {
  provider: string;
  api_key_masked: string;
  base_url: string;
  model: string;
  config_path: string;
  saved_models?: string[];
  default_provider_id?: string;
  model_providers?: ModelProviderRow[];
}

export interface SaveSettingsRequest {
  provider: string;
  api_key: string;
  base_url: string;
  model: string;
  saved_models?: string[];
  model_providers?: Array<{
    id: string;
    label: string;
    provider: string;
    api_key: string;
    base_url: string;
    model: string;
    saved_models: string[];
  }>;
  default_provider_id?: string;
}

export type WebEventType =
  | "text"
  | "thinking"
  | "tool_start"
  | "tool_end"
  | "error"
  | "permission_request"
  | "done"
  | "hook_start"
  | "hook_end"
  | "background_status"
  | "mode_change"
  | "subagent_start"
  | "subagent_end"
  | "plan_mode_suggest"
  | "tool_progress"
  | "todo_update"
  | "image_stored"
  | "document_attached"
  | "content_replaced"
  | "plan_updated"
  | "ask_user"
  | "compact_start"
  | "compact_end";

export interface TextEvent {
  type: "text";
  content: string;
}

export interface ThinkingEvent {
  type: "thinking";
  content: string;
}

export interface ToolStartEvent {
  type: "tool_start";
  name: string;
  input: string;
}

export interface ToolEndEvent {
  type: "tool_end";
  name: string;
  output: string;
  error: boolean;
}

export interface ErrorEvent {
  type: "error";
  content: string;
}

export interface PermissionRequestEvent {
  type: "permission_request";
  tool_name: string;
  input: string;
}

export interface DoneEvent {
  type: "done";
}

export interface HookStartEvent {
  type: "hook_start";
  name: string;
}

export interface HookEndEvent {
  type: "hook_end";
  name: string;
  output: string;
  error: boolean;
}

export interface BackgroundStatusEvent {
  type: "background_status";
  name: string;
  status: string;
}

export interface ModeChangeEvent {
  type: "mode_change";
  content: string; // "plan" | "normal"
}

export interface SubagentStartEvent {
  type: "subagent_start";
  name: string;
  content: string;
}

export interface SubagentEndEvent {
  type: "subagent_end";
  name: string;
  status: string;
}

export interface PlanModeSuggestEvent {
  type: "plan_mode_suggest";
  content: string; // reason from AI
}

export interface ToolProgressEvent {
  type: "tool_progress";
  name: string;
  content: string;
}

export interface TodoUpdateEvent {
  type: "todo_update";
  content: string; // JSON array of TodoItem
}

export interface TodoItem {
  id?: string;
  content: string;
  activeForm: string;
  status: "pending" | "in_progress" | "completed";
}

export interface ImageStoredEvent {
  type: "image_stored";
  name: string;
  content: string;
}

export interface DocumentAttachedEvent {
  type: "document_attached";
  name: string;
  content: string;
}

export interface AskUserOption {
  label: string;
  description?: string;
}

export interface AskUserQuestionItem {
  question: string;
  options: AskUserOption[];
}

export interface AskUserEvent {
  type: "ask_user";
  name: string; // tool_use_id
  content: string; // JSON: { questions: AskUserQuestionItem[] }
}

export interface PlanUpdatedEvent {
  type: "plan_updated";
  name: string; // slug
  content: string; // file path
}

export interface CompactStartEvent {
  type: "compact_start";
  content: string;
}

export interface CompactEndEvent {
  type: "compact_end";
  content: string;
}

export type WebEvent =
  | TextEvent
  | ThinkingEvent
  | ToolStartEvent
  | ToolEndEvent
  | ErrorEvent
  | PermissionRequestEvent
  | DoneEvent
  | HookStartEvent
  | HookEndEvent
  | BackgroundStatusEvent
  | ModeChangeEvent
  | SubagentStartEvent
  | SubagentEndEvent
  | PlanModeSuggestEvent
  | ToolProgressEvent
  | TodoUpdateEvent
  | ImageStoredEvent
  | DocumentAttachedEvent
  | AskUserEvent
  | PlanUpdatedEvent
  | CompactStartEvent
  | CompactEndEvent;

export interface ModelInfo {
  id: string;
  name: string;
}

export interface ModelsResponse {
  models: ModelInfo[];
  error?: string | null;
}

export interface DiscoverModelsRequest {
  api_key?: string;
  base_url?: string;
  provider_id?: string;
}

export interface SkillInfo {
  name: string;
  path: string;
  description: string;
}

export interface SkillsResponse {
  skills: SkillInfo[];
  skill_dirs: string[];
}

export interface McpServerInfo {
  name: string;
  server_type: string;
  command: string;
  args: string[];
  url: string;
  status: "connected" | "disconnected" | "error" | "disabled";
  enabled: boolean;
  error?: string;
  tools: string[];
}

export interface ConnectMcpServerResponse {
  success: boolean;
  status: string;
  error?: string;
  tools: string[];
}

export interface McpServersResponse {
  servers: McpServerInfo[];
  config_path: string;
}

export interface BuiltinBrowserMcpResponse {
  enabled: boolean;
  auto_start: boolean;
  status: "connected" | "disconnected" | "disabled" | "error";
  bridge_host: string;
  bridge_port: number;
  bridge_path: string;
  pairing_token: string;
  ws_url: string;
  tools: string[];
  error?: string | null;
}

export interface SaveBuiltinBrowserMcpRequest {
  enabled: boolean;
  auto_start: boolean;
  bridge_port?: number | null;
  pairing_token: string;
  regenerate_token?: boolean;
}

export interface SaveMcpServerRequest {
  name: string;
  server_type: string;
  command: string;
  args: string[];
  url: string;
  enabled?: boolean;
}

// Memory types

export interface MemoryTypeInfo {
  type: string;
  title: string;
  description: string;
  has_content: boolean;
  preview: string;
}

export interface MemoryListResponse {
  types: MemoryTypeInfo[];
  enabled: boolean;
  memory_dir: string;
}

export interface MemoryContentResponse {
  type: string;
  title: string;
  content: string;
  template: string;
}

// Model roles

export interface ModelRoleConfig {
  provider_id: string;
  model: string;
  enabled: boolean;
}

export interface ModelRolesResponse {
  verification: ModelRoleConfig;
  memory: ModelRoleConfig;
}

export interface ToolBlock {
  type: "tool_start" | "tool_end";
  name: string;
  input?: string;
  output?: string;
  error?: boolean;
  status: "running" | "success" | "error";
}

export type MessageStep =
  | { type: "text"; content: string }
  | { type: "tool_group"; blocks: ToolBlock[] };

// Playbook types

export interface PlaybookDocInfo {
  filename: string;
  title: string;
}

export interface PlaybookCategoryInfo {
  name: string;
  description: string;
  documents: PlaybookDocInfo[];
}

export interface PlaybooksResponse {
  categories: PlaybookCategoryInfo[];
  playbooks_dir: string;
}

export interface PlaybookContentResponse {
  category: string;
  filename: string;
  content: string;
  template: string;
}

export interface Artifact {
  fileName: string;
  contentType: "document" | "image";
  content: string;
  fileDataUrl?: string;
}

export interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolBlocks: ToolBlock[];
  steps: MessageStep[];
  streaming?: boolean;
  isPlan?: boolean;
  thinking?: string;
  images?: { url: string; alt: string }[];
  files?: {
    filename: string;
    category: string;
    size: number;
    fileId: string;
    markdownPath?: string;
    cachedPath?: string;
  }[];
}

// ─── Skill Store Types ───

export interface SkillStoreInfo {
  id: string;
  display_name: string;
  description: string;
  category: string | null;
  body_path: string | null;
  body_hash: string | null;
  pinned: boolean;
  enabled: boolean;
  trigger_terms: string[] | string | null;
  metadata: string | null;
  created_at: number;
  updated_at: number;
  has_embeddings?: boolean;
}

export interface SkillStoreListResponse {
  skills: SkillStoreInfo[];
  total: number;
}

export interface SkillStoreDetailResponse extends SkillStoreInfo {
  body_content: string;
  entities: { id: string; name: string; entity_type: string; relation: string | null }[];
  edges: { source_id: string; target_id: string; edge_type: string; weight: number }[];
}

export interface SkillStoreImportResponse {
  added: string[];
  updated: string[];
  disabled: string[];
  errors: { path: string; reason: string }[];
  summary: string;
}

export interface SkillStoreStatsResponse {
  enabled: boolean;
  available?: boolean;
  db_path: string;
  total?: number;
  pinned?: number;
  edge_count?: number;
  entity_count?: number;
  has_embeddings?: number;
  categories?: Record<string, number>;
}

export interface SkillRelationsResponse {
  nodes: { id: string; name: string; category: string | null }[];
  edges: { source_id: string; target_id: string; edge_type: string; weight: number }[];
}

// ── Skill Market (ClawHub) ──

export interface MarketSkillInfo {
  slug: string;
  name: string;
  description: string;
  author: string;
  downloads: number;
  stars: number;
  staff_pick: boolean;
  created_at: string;
  version: string;
}

export interface MarketSearchResponse {
  skills: MarketSkillInfo[];
  total: number;
}

export interface MarketInstallResponse {
  ok: boolean;
  skill_id: string;
  slug: string;
  path: string;
  message: string;
}

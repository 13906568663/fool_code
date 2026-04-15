"""HTTP API request/response models — used by the FastAPI route layer."""

from __future__ import annotations

from pydantic import BaseModel, Field

from fool_code.types import ChatMessage, ModelInfo, SessionListItem


# ---------- Status ----------

class StatusResponse(BaseModel):
    model: str
    status: str
    active_session: str
    configured: bool


# ---------- Chat ----------

class ChatRequest(BaseModel):
    message: str
    model: str | None = None
    images: list[ImageAttachment] | None = None


class ImageAttachment(BaseModel):
    id: str
    data: str           # base64 encoded
    media_type: str = "image/png"


# ---------- Sessions ----------

class SessionsResponse(BaseModel):
    sessions: list[SessionListItem]
    active_id: str


class ProviderSummary(BaseModel):
    id: str
    label: str


class SessionDetailResponse(BaseModel):
    id: str
    title: str
    messages: list[ChatMessage]
    chat_model: str | None = None
    chat_provider_id: str | None = None
    default_provider_id: str = ""
    providers: list[ProviderSummary] = Field(default_factory=list)
    default_model: str = ""
    saved_models: list[str] = Field(default_factory=list)
    effective_model: str = ""
    plan_slug: str | None = None
    plan_status: str = "none"
    plan_todos: list[dict] = Field(default_factory=list)


class SetSessionModelRequest(BaseModel):
    """Empty string clears override (use workspace default)."""
    model: str


class SetSessionProviderRequest(BaseModel):
    """Empty string clears override (use workspace default provider)."""
    provider_id: str = ""


# ---------- Settings ----------

class ModelProviderRowOut(BaseModel):
    id: str
    label: str = ""
    provider: str = "openai"
    api_key_masked: str = ""
    base_url: str = ""
    model: str = ""
    saved_models: list[str] = Field(default_factory=list)


class SettingsResponse(BaseModel):
    provider: str
    api_key_masked: str = ""
    base_url: str = ""
    model: str = ""
    config_path: str = ""
    saved_models: list[str] = Field(default_factory=list)
    default_provider_id: str = ""
    model_providers: list[ModelProviderRowOut] = Field(default_factory=list)


class ModelProviderRowIn(BaseModel):
    id: str = ""
    label: str = ""
    provider: str = "openai"
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    saved_models: list[str] = Field(default_factory=list)


class SaveSettingsRequest(BaseModel):
    provider: str = "openai"
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    saved_models: list[str] | None = None
    model_providers: list[ModelProviderRowIn] | None = None
    default_provider_id: str | None = None


# ---------- Models ----------

class DiscoverModelsRequest(BaseModel):
    api_key: str = ""
    base_url: str = ""
    provider_id: str = ""


class ModelsResponse(BaseModel):
    models: list[ModelInfo]
    error: str | None = None


# ---------- Skills ----------

class SkillInfo(BaseModel):
    name: str
    path: str
    description: str


class SkillsResponse(BaseModel):
    skills: list[SkillInfo]
    skill_dirs: list[str]


# ---------- MCP ----------

class McpServerInfo(BaseModel):
    name: str
    server_type: str
    command: str
    args: list[str]
    url: str
    status: str
    enabled: bool = True
    error: str | None = None
    tools: list[str] = Field(default_factory=list)


class McpServersResponse(BaseModel):
    servers: list[McpServerInfo]
    config_path: str


class BuiltinBrowserMcpResponse(BaseModel):
    enabled: bool
    auto_start: bool
    status: str
    bridge_host: str
    bridge_port: int
    bridge_path: str
    pairing_token: str
    ws_url: str
    tools: list[str] = Field(default_factory=list)
    error: str | None = None


class SaveBuiltinBrowserMcpRequest(BaseModel):
    enabled: bool = True
    auto_start: bool = True
    bridge_port: int | None = None
    pairing_token: str = ""
    regenerate_token: bool = False


class SaveMcpServerRequest(BaseModel):
    name: str
    server_type: str
    command: str
    args: list[str] = Field(default_factory=list)
    url: str = ""
    enabled: bool = True


class ToggleMcpServerRequest(BaseModel):
    name: str
    enabled: bool


class DisconnectMcpServerRequest(BaseModel):
    name: str


class DeleteMcpServerRequest(BaseModel):
    name: str


class ConnectMcpServerRequest(BaseModel):
    name: str


class ConnectMcpServerResponse(BaseModel):
    success: bool
    status: str
    error: str | None = None
    tools: list[str] = Field(default_factory=list)


# ---------- Workspace ----------

class WorkspaceResponse(BaseModel):
    workspace_root: str
    app_data_root: str
    config_path: str
    sessions_path: str
    skills_path: str


class SetWorkspaceRequest(BaseModel):
    workspace_root: str


# ---------- Permission ----------

class PermissionDecisionRequest(BaseModel):
    decision: str


class PermissionModeResponse(BaseModel):
    mode: str


class SetPermissionModeRequest(BaseModel):
    mode: str


# ---------- Memory ----------

class MemoryTypeInfo(BaseModel):
    type: str
    title: str
    description: str
    has_content: bool
    preview: str = ""


class MemoryListResponse(BaseModel):
    types: list[MemoryTypeInfo]
    enabled: bool
    memory_dir: str


class MemoryContentResponse(BaseModel):
    type: str
    title: str
    content: str
    template: str = ""


class SaveMemoryRequest(BaseModel):
    content: str


class ModelRoleConfig(BaseModel):
    provider_id: str = ""
    model: str = ""
    enabled: bool = True


class ModelRolesResponse(BaseModel):
    verification: ModelRoleConfig = ModelRoleConfig()
    memory: ModelRoleConfig = ModelRoleConfig()


class SaveModelRolesRequest(BaseModel):
    verification: ModelRoleConfig | None = None
    memory: ModelRoleConfig | None = None


# ---------- Playbook ----------

class PlaybookDocInfo(BaseModel):
    filename: str
    title: str


class PlaybookCategoryInfo(BaseModel):
    name: str
    description: str = ""
    documents: list[PlaybookDocInfo] = Field(default_factory=list)


class PlaybooksResponse(BaseModel):
    categories: list[PlaybookCategoryInfo]
    playbooks_dir: str


class PlaybookContentResponse(BaseModel):
    category: str
    filename: str
    content: str
    template: str = ""


class SavePlaybookRequest(BaseModel):
    content: str


class CreatePlaybookCategoryRequest(BaseModel):
    name: str
    description: str = ""

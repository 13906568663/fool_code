import { useState, useEffect, useCallback } from "react";
import {
  X,
  Cpu,
  Sparkles,
  Network,
  Plus,
  Trash2,
  FolderOpen,
  ChevronDown,
  ChevronRight,
  HardDrive,
  RefreshCw,
  Loader2,
  Plug,
  Brain,
  Save,
  BookOpen,
  FileText,
  Copy,
  Check,
  RotateCcw,
} from "lucide-react";
import type {
  SkillInfo,
  BuiltinBrowserMcpResponse,
  McpServerInfo,
  SaveBuiltinBrowserMcpRequest,
  SaveMcpServerRequest,
  WorkspaceResponse,
  MemoryTypeInfo,
  PlaybookCategoryInfo,
} from "../types";
import * as api from "../services/api";
import ModelSettingsTab from "./ModelSettingsTab";
import ConfirmDialog from "./ConfirmDialog";

interface SettingsPanelProps {
  open: boolean;
  onClose: () => void;
  onModelChange?: (model: string) => void;
}

type TabId = "workspace" | "model" | "memory" | "playbooks" | "skills" | "mcp";

const TABS: { id: TabId; label: string; icon: typeof Cpu }[] = [
  { id: "workspace", label: "工作区", icon: HardDrive },
  { id: "model", label: "模型配置", icon: Cpu },
  { id: "memory", label: "记忆", icon: Brain },
  { id: "playbooks", label: "经验文档", icon: BookOpen },
  { id: "skills", label: "Skills", icon: Sparkles },
  { id: "mcp", label: "MCP 服务", icon: Network },
];

export default function SettingsPanel({
  open,
  onClose,
  onModelChange,
}: SettingsPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>("workspace");

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/25 z-[100]"
        onClick={onClose}
      />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white border border-gray-200 rounded-2xl w-[640px] max-w-[92vw] max-h-[85vh] overflow-hidden z-[101] shadow-2xl flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <h3 className="text-base font-semibold">设置</h3>
          <button
            onClick={onClose}
            className="bg-transparent border-none text-gray-400 cursor-pointer p-1 rounded-md hover:bg-gray-100 hover:text-gray-700"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex border-b border-gray-200">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-4 py-2.5 text-sm border-b-2 transition-colors cursor-pointer bg-transparent ${
                  activeTab === tab.id
                    ? "border-blue-600 text-blue-600 font-medium"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
              >
                <Icon size={15} />
                {tab.label}
              </button>
            );
          })}
        </div>

        <div className="flex-1 overflow-y-auto">
          {activeTab === "workspace" && <WorkspaceTab />}
          {activeTab === "model" && (
            <ModelSettingsTab onClose={onClose} onModelChange={onModelChange} />
          )}
          {activeTab === "memory" && <MemoryTab />}
          {activeTab === "playbooks" && <PlaybooksTab />}
          {activeTab === "skills" && <SkillsTab />}
          {activeTab === "mcp" && <McpTab />}
        </div>
      </div>
    </>
  );
}

function MemoryTab() {
  const [types, setTypes] = useState<MemoryTypeInfo[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [memoryDir, setMemoryDir] = useState("");
  const [loading, setLoading] = useState(true);
  const [editingType, setEditingType] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{
    text: string;
    color: string;
  } | null>(null);

  const loadMemory = useCallback(() => {
    setLoading(true);
    api.getMemoryList().then((data) => {
      setTypes(data.types);
      setEnabled(data.enabled);
      setMemoryDir(data.memory_dir);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    loadMemory();
  }, [loadMemory]);

  const handleToggle = async () => {
    const next = !enabled;
    await api.toggleMemory(next);
    setEnabled(next);
  };

  const handleEdit = async (memType: string) => {
    const data = await api.getMemory(memType);
    setEditContent(data.content || data.template);
    setEditingType(memType);
    setStatus(null);
  };

  const handleSave = async () => {
    if (!editingType) return;
    setSaving(true);
    setStatus(null);
    try {
      await api.saveMemory(editingType, editContent);
      setStatus({ text: "已保存", color: "text-green-600" });
      setEditingType(null);
      loadMemory();
    } catch (e) {
      setStatus({
        text: `保存失败: ${e instanceof Error ? e.message : "未知错误"}`,
        color: "text-red-600",
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="p-8 text-center text-gray-400 text-sm">加载中...</div>
    );
  }

  if (editingType) {
    const spec = types.find((t) => t.type === editingType);
    return (
      <div className="p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-gray-700">
            编辑 — {spec?.title || editingType}
          </div>
          <button
            onClick={() => {
              setEditingType(null);
              setStatus(null);
            }}
            className="text-xs text-gray-500 hover:text-gray-700 bg-transparent border border-gray-200 rounded-lg px-3 py-1.5 cursor-pointer hover:bg-gray-50 transition-colors"
          >
            返回
          </button>
        </div>
        {spec && (
          <div className="text-xs text-gray-400">{spec.description}</div>
        )}
        <textarea
          value={editContent}
          onChange={(e) => setEditContent(e.target.value)}
          className="w-full h-64 bg-gray-50 border border-gray-200 rounded-lg p-3 text-sm font-mono outline-none focus:border-blue-600 resize-y leading-relaxed"
          placeholder="在这里编写你的记忆内容（Markdown 格式）..."
        />
        <div className="flex items-center gap-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 bg-blue-600 text-white border-none rounded-lg px-4 py-2 cursor-pointer text-sm font-medium hover:opacity-85 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Save size={14} />
            {saving ? "保存中..." : "保存"}
          </button>
          <button
            onClick={() => {
              setEditingType(null);
              setStatus(null);
            }}
            className="bg-gray-100 text-gray-700 border border-gray-200 rounded-lg px-4 py-2 cursor-pointer text-sm hover:border-gray-400 transition-all"
          >
            取消
          </button>
          {status && (
            <span className={`text-xs ${status.color}`}>{status.text}</span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="p-5 space-y-4">
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
        <div className="text-sm text-amber-800 font-medium mb-1">
          用户记忆系统
        </div>
        <div className="text-xs text-amber-600 leading-relaxed">
          记忆帮助 AI 了解你的背景和偏好，从而提供更个性化的回答。
          记忆内容会在每次对话时注入到系统提示中。
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold text-gray-700">记忆开关</div>
        <button
          onClick={handleToggle}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors cursor-pointer border-none ${
            enabled ? "bg-blue-600" : "bg-gray-300"
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              enabled ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
      </div>
      {!enabled && (
        <div className="text-xs text-gray-400">
          记忆已关闭，AI 不会读取你的用户画像和协作偏好。
        </div>
      )}

      <div>
        <div className="text-sm font-semibold text-gray-700 mb-2">
          记忆内容
        </div>
        <div className="space-y-2">
          {types.map((t) => (
            <div
              key={t.type}
              className="border border-gray-200 rounded-lg p-3 hover:border-gray-300 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Brain size={14} className="text-amber-500" />
                  <span className="text-sm font-medium text-gray-800">
                    {t.title}
                  </span>
                  {t.has_content && (
                    <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded">
                      已配置
                    </span>
                  )}
                </div>
                <button
                  onClick={() => handleEdit(t.type)}
                  className="text-xs text-blue-600 hover:text-blue-800 bg-transparent border border-blue-200 rounded-lg px-3 py-1.5 cursor-pointer hover:bg-blue-50 transition-colors"
                >
                  {t.has_content ? "编辑" : "设置"}
                </button>
              </div>
              <div className="text-xs text-gray-400 mt-1 ml-[22px]">
                {t.description}
              </div>
              {t.preview && (
                <div className="text-xs text-gray-500 mt-1.5 ml-[22px] bg-gray-50 rounded px-2 py-1.5 italic">
                  {t.preview}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <ModelRolesSection />

      {memoryDir && (
        <div className="bg-gray-50 rounded-lg p-3">
          <label className="block text-xs text-gray-400 mb-0.5">
            存储目录
          </label>
          <div className="text-xs text-gray-500 break-all font-mono">
            {memoryDir}
          </div>
        </div>
      )}
    </div>
  );
}

function ModelRolesSection() {
  const [verifyModel, setVerifyModel] = useState("");
  const [verifyProviderId, setVerifyProviderId] = useState("");
  const [verifyEnabled, setVerifyEnabled] = useState(false);
  const [memoryModel, setMemoryModel] = useState("");
  const [memoryProviderId, setMemoryProviderId] = useState("");
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [providers, setProviders] = useState<
    {
      id: string;
      label: string;
      model: string;
      isDefault: boolean;
      providerType: string;
    }[]
  >([]);
  const [modelsByProvider, setModelsByProvider] = useState<
    Record<string, { id: string; name: string }[]>
  >({});
  const [defaultProviderId, setDefaultProviderId] = useState("");
  const [discoverLoadingId, setDiscoverLoadingId] = useState<string | null>(
    null
  );
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const [status, setStatus] = useState<{
    text: string;
    color: string;
  } | null>(null);

  useEffect(() => {
    Promise.all([api.getModelRoles(), api.getSettings()]).then(
      ([roles, settings]) => {
        const dpid = settings.default_provider_id || "";
        setDefaultProviderId(dpid);

        const provs = (settings.model_providers || []).map((p) => ({
          id: p.id,
          label: p.label || p.id,
          model: p.model || "",
          isDefault: p.id === dpid,
          providerType: p.provider || "openai",
        }));
        setProviders(provs);

        const fallbackPid = dpid || (provs[0]?.id || "");
        setVerifyModel(roles.verification?.model || "");
        setVerifyProviderId(roles.verification?.provider_id || fallbackPid);
        setVerifyEnabled(roles.verification?.enabled ?? false);
        setMemoryModel(roles.memory?.model || "");
        setMemoryProviderId(roles.memory?.provider_id || fallbackPid);

        const providerTypes = [
          ...new Set((settings.model_providers || []).map((p) => p.provider)),
        ];
        for (const pt of providerTypes) {
          api.getModels(pt).then((data) => {
            setModelsByProvider((prev) => {
              const next = { ...prev };
              for (const p of settings.model_providers || []) {
                if (p.provider === pt) {
                  const combined = [
                    ...data.models,
                    ...(p.saved_models || [])
                      .filter((sm) => !data.models.some((m) => m.id === sm))
                      .map((sm) => ({ id: sm, name: sm })),
                  ];
                  next[p.id] = combined;
                }
              }
              return next;
            });
          });
        }

        setLoaded(true);
      }
    );
  }, []);

  const handleDiscover = async (providerId: string) => {
    const prov = providers.find((p) => p.id === providerId);
    if (!prov || prov.providerType !== "openai") {
      setDiscoverError("仅 OpenAI 兼容接口支持拉取模型列表");
      return;
    }
    setDiscoverLoadingId(providerId);
    setDiscoverError(null);
    try {
      const res = await api.discoverModels({ provider_id: providerId });
      if (res.error) {
        setDiscoverError(res.error);
      } else if (res.models.length > 0) {
        setModelsByProvider((prev) => ({
          ...prev,
          [providerId]: res.models,
        }));
        setStatus({
          text: `已获取 ${res.models.length} 个模型`,
          color: "text-green-600",
        });
      }
    } catch (e) {
      setDiscoverError(e instanceof Error ? e.message : "拉取失败");
    } finally {
      setDiscoverLoadingId(null);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setStatus(null);
    try {
      await api.saveModelRoles({
        verification: {
          provider_id: verifyProviderId,
          model: verifyModel,
          enabled: verifyEnabled,
        },
        memory: {
          provider_id: memoryProviderId,
          model: memoryModel,
          enabled: true,
        },
      });
      setStatus({ text: "已保存", color: "text-green-600" });
    } catch {
      setStatus({ text: "保存失败", color: "text-red-600" });
    } finally {
      setSaving(false);
    }
  };

  if (!loaded) return null;

  const defaultProv = providers.find((p) => p.isDefault);
  const defaultLabel = defaultProv?.label || "未配置";
  const defaultModel = defaultProv?.model || "未配置";

  const resolveEffective = (pid: string, model: string) => {
    const prov = pid ? providers.find((p) => p.id === pid) : defaultProv;
    const provLabel = prov?.label || defaultLabel;
    const modelName = model || prov?.model || defaultModel;
    return { provLabel, modelName };
  };

  const modelsForProvider = (pid: string) => {
    const effectivePid = pid || defaultProviderId;
    return modelsByProvider[effectivePid] || [];
  };

  const renderRoleCard = (opts: {
    icon: typeof Cpu;
    iconColor: string;
    title: string;
    badge: string;
    badgeBg: string;
    badgeText: string;
    description: string;
    providerId: string;
    onProviderChange: (id: string) => void;
    model: string;
    onModelChange: (m: string) => void;
    toggleEnabled?: boolean;
    enabled?: boolean;
    onToggle?: () => void;
  }) => {
    const Icon = opts.icon;
    const models = modelsForProvider(opts.providerId);
    const isCustom =
      opts.model !== "" && !models.some((m) => m.id === opts.model);
    const disabled = opts.toggleEnabled !== undefined && !opts.enabled;
    const eff = resolveEffective(opts.providerId, opts.model);

    return (
      <div
        className={`border rounded-lg p-3 transition-colors ${
          disabled
            ? "border-gray-100 bg-gray-50/50 opacity-60"
            : "border-gray-200"
        }`}
      >
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <Icon size={14} className={opts.iconColor} />
            <span className="text-sm font-medium text-gray-700">
              {opts.title}
            </span>
            <span
              className={`text-[10px] ${opts.badgeBg} ${opts.badgeText} px-1.5 py-0.5 rounded`}
            >
              {opts.badge}
            </span>
          </div>
          {opts.toggleEnabled !== undefined && (
            <button
              onClick={opts.onToggle}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer border-none ${
                opts.enabled ? "bg-blue-600" : "bg-gray-300"
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                  opts.enabled ? "translate-x-[18px]" : "translate-x-[3px]"
                }`}
              />
            </button>
          )}
        </div>

        <div className="text-xs text-gray-400 mb-2">{opts.description}</div>

        {!disabled && (
          <>
            <div className="bg-gray-50 border border-gray-100 rounded-md px-2.5 py-1.5 mb-3 flex items-center gap-1.5">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-500 shrink-0" />
              <span className="text-[11px] text-gray-500">
                实际使用：
                <span className="font-medium text-gray-700">
                  {eff.provLabel}
                </span>
                {" / "}
                <span className="font-mono text-gray-700">
                  {eff.modelName}
                </span>
              </span>
            </div>

            <div className="space-y-2">
              <div>
                <label className="block text-[11px] font-medium text-gray-500 mb-1">
                  供应商
                </label>
                <div className="relative">
                  <select
                    value={opts.providerId}
                    onChange={(e) => {
                      opts.onProviderChange(e.target.value);
                      opts.onModelChange("");
                    }}
                    className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-blue-600 cursor-pointer appearance-none pr-8"
                  >
                    {providers.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.label}
                        {p.isDefault ? "（当前默认）" : ""}
                      </option>
                    ))}
                  </select>
                  <ChevronDown
                    size={14}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
                  />
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-[11px] font-medium text-gray-500">
                    模型
                  </label>
                  {providers.find((p) => p.id === (opts.providerId || defaultProviderId))
                    ?.providerType === "openai" && (
                    <button
                      type="button"
                      onClick={() =>
                        handleDiscover(opts.providerId || defaultProviderId)
                      }
                      disabled={
                        discoverLoadingId ===
                        (opts.providerId || defaultProviderId)
                      }
                      className="flex items-center gap-1 text-[11px] text-purple-600 bg-transparent border-none cursor-pointer hover:text-purple-800 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {discoverLoadingId ===
                      (opts.providerId || defaultProviderId) ? (
                        <>
                          <Loader2 size={11} className="animate-spin" />
                          拉取中…
                        </>
                      ) : (
                        <>
                          <RefreshCw size={11} />
                          拉取模型列表
                        </>
                      )}
                    </button>
                  )}
                </div>
                {discoverError &&
                  discoverLoadingId === null && (
                    <div className="text-[11px] text-red-500 mb-1">
                      {discoverError}
                    </div>
                  )}
                {!isCustom ? (
                  <div className="relative">
                    <select
                      value={opts.model}
                      onChange={(e) => {
                        if (e.target.value === "__custom__") {
                          opts.onModelChange("");
                        } else {
                          opts.onModelChange(e.target.value);
                        }
                      }}
                      className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-blue-600 cursor-pointer appearance-none pr-8"
                    >
                      <option value="">
                        与供应商默认相同（
                        {(opts.providerId
                          ? providers.find((p) => p.id === opts.providerId)
                              ?.model
                          : defaultProv?.model) || "未设置"}
                        ）
                      </option>
                      {models.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name}
                          {m.name !== m.id ? ` (${m.id})` : ""}
                        </option>
                      ))}
                      <option value="__custom__">自定义模型名称...</option>
                    </select>
                    <ChevronDown
                      size={14}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
                    />
                  </div>
                ) : (
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={opts.model}
                      onChange={(e) => opts.onModelChange(e.target.value)}
                      placeholder="模型 ID"
                      className="flex-1 bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-blue-600 font-mono"
                    />
                    <button
                      type="button"
                      onClick={() => opts.onModelChange("")}
                      className="text-xs text-blue-600 bg-transparent border-none cursor-pointer whitespace-nowrap"
                    >
                      选预设
                    </button>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    );
  };

  return (
    <div>
      <div className="text-sm font-semibold text-gray-700 mb-2">
        子代理模型
      </div>
      <div className="text-xs text-gray-400 mb-3">
        为不同任务指定独立的供应商和模型。不指定时复用默认供应商的主模型。
      </div>
      <div className="space-y-2">
        {renderRoleCard({
          icon: Cpu,
          iconColor: "text-blue-500",
          title: "验证模型",
          badge: "代码审查",
          badgeBg: "bg-blue-50",
          badgeText: "text-blue-600",
          description:
            "在任务完成后自动进行代码审查和验证，会消耗额外的 Token。",
          providerId: verifyProviderId,
          onProviderChange: setVerifyProviderId,
          model: verifyModel,
          onModelChange: setVerifyModel,
          toggleEnabled: true,
          enabled: verifyEnabled,
          onToggle: () => setVerifyEnabled((v) => !v),
        })}
        {renderRoleCard({
          icon: Brain,
          iconColor: "text-amber-500",
          title: "记忆模型",
          badge: "画像提取",
          badgeBg: "bg-amber-50",
          badgeText: "text-amber-600",
          description: "自动从对话中提取用户偏好和习惯，用于后续个性化回答。",
          providerId: memoryProviderId,
          onProviderChange: setMemoryProviderId,
          model: memoryModel,
          onModelChange: setMemoryModel,
        })}
      </div>
      <div className="flex items-center gap-2 mt-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-1.5 bg-blue-600 text-white border-none rounded-lg px-4 py-2 cursor-pointer text-sm font-medium hover:opacity-85 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Save size={14} />
          {saving ? "保存中..." : "保存模型配置"}
        </button>
        {status && (
          <span className={`text-xs ${status.color}`}>{status.text}</span>
        )}
      </div>
    </div>
  );
}

function PlaybooksTab() {
  const [categories, setCategories] = useState<PlaybookCategoryInfo[]>([]);
  const [playbooksDir, setPlaybooksDir] = useState("");
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const [showAddCat, setShowAddCat] = useState(false);
  const [newCatName, setNewCatName] = useState("");
  const [newCatDesc, setNewCatDesc] = useState("");

  const [showAddDoc, setShowAddDoc] = useState<string | null>(null);
  const [newDocName, setNewDocName] = useState("");

  const [editingDoc, setEditingDoc] = useState<{
    category: string;
    filename: string;
  } | null>(null);
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{
    text: string;
    color: string;
  } | null>(null);
  const [pbConfirmDialog, setPbConfirmDialog] = useState<{
    title: string; message: string; variant: "danger" | "warning" | "default";
    confirmText: string; action: () => void;
  } | null>(null);

  const loadPlaybooks = useCallback(() => {
    setLoading(true);
    api.getPlaybooks().then((data) => {
      setCategories(data.categories);
      setPlaybooksDir(data.playbooks_dir);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    loadPlaybooks();
  }, [loadPlaybooks]);

  const handleCreateCategory = async () => {
    if (!newCatName.trim()) return;
    setSaving(true);
    try {
      await api.createPlaybookCategory(newCatName.trim(), newCatDesc.trim());
      setNewCatName("");
      setNewCatDesc("");
      setShowAddCat(false);
      loadPlaybooks();
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteCategory = (name: string) => {
    setPbConfirmDialog({
      title: "删除分类",
      message: `确定删除分类「${name}」及其所有文档？此操作不可撤销。`,
      variant: "danger",
      confirmText: "删除",
      action: async () => {
        setPbConfirmDialog(null);
        await api.deletePlaybookCategory(name);
        loadPlaybooks();
      },
    });
  };

  const handleNewDoc = async (category: string) => {
    if (!newDocName.trim()) return;
    const filename = newDocName.trim().endsWith(".md")
      ? newDocName.trim()
      : `${newDocName.trim()}.md`;
    const { template } = await api.getPlaybookTemplate();
    const content = template.replace("新经验文档", newDocName.trim().replace(/\.md$/, ""));
    await api.savePlaybook(category, filename, content);
    setNewDocName("");
    setShowAddDoc(null);
    loadPlaybooks();
    setEditingDoc({ category, filename });
    setEditContent(content);
  };

  const handleEditDoc = async (category: string, filename: string) => {
    const data = await api.getPlaybook(category, filename);
    setEditContent(data.content);
    setEditingDoc({ category, filename });
    setStatus(null);
  };

  const handleSaveDoc = async () => {
    if (!editingDoc) return;
    setSaving(true);
    setStatus(null);
    try {
      await api.savePlaybook(editingDoc.category, editingDoc.filename, editContent);
      setStatus({ text: "已保存", color: "text-green-600" });
      setEditingDoc(null);
      loadPlaybooks();
    } catch (e) {
      setStatus({
        text: `保存失败: ${e instanceof Error ? e.message : "未知错误"}`,
        color: "text-red-600",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteDoc = (category: string, filename: string) => {
    setPbConfirmDialog({
      title: "删除文档",
      message: `确定删除「${filename}」？此操作不可撤销。`,
      variant: "danger",
      confirmText: "删除",
      action: async () => {
        setPbConfirmDialog(null);
        await api.deletePlaybook(category, filename);
        loadPlaybooks();
      },
    });
  };

  const toggleExpanded = (name: string) => {
    setExpanded((prev) => ({ ...prev, [name]: !prev[name] }));
  };

  if (loading) {
    return (
      <div className="p-8 text-center text-gray-400 text-sm">加载中...</div>
    );
  }

  if (editingDoc) {
    return (
      <div className="p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-gray-700">
            编辑 — {editingDoc.category} / {editingDoc.filename}
          </div>
          <button
            onClick={() => {
              setEditingDoc(null);
              setStatus(null);
            }}
            className="text-xs text-gray-500 hover:text-gray-700 bg-transparent border border-gray-200 rounded-lg px-3 py-1.5 cursor-pointer hover:bg-gray-50 transition-colors"
          >
            返回
          </button>
        </div>
        <textarea
          value={editContent}
          onChange={(e) => setEditContent(e.target.value)}
          className="w-full h-72 bg-gray-50 border border-gray-200 rounded-lg p-3 text-sm font-mono outline-none focus:border-blue-600 resize-y leading-relaxed"
          placeholder="在这里编写经验文档（Markdown 格式）..."
        />
        <div className="flex items-center gap-2">
          <button
            onClick={handleSaveDoc}
            disabled={saving}
            className="flex items-center gap-1.5 bg-blue-600 text-white border-none rounded-lg px-4 py-2 cursor-pointer text-sm font-medium hover:opacity-85 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Save size={14} />
            {saving ? "保存中..." : "保存"}
          </button>
          <button
            onClick={() => {
              setEditingDoc(null);
              setStatus(null);
            }}
            className="bg-gray-100 text-gray-700 border border-gray-200 rounded-lg px-4 py-2 cursor-pointer text-sm hover:border-gray-400 transition-all"
          >
            取消
          </button>
          {status && (
            <span className={`text-xs ${status.color}`}>{status.text}</span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="p-5 space-y-4">
      <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3">
        <div className="text-sm text-emerald-800 font-medium mb-1">
          经验文档库
        </div>
        <div className="text-xs text-emerald-600 leading-relaxed">
          将成功的操作经验整理成文档，AI 在遇到类似任务时可以主动查阅参考。
          按分类组织，每个分类下可以有多篇 Markdown 文档。
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold text-gray-700">
          分类 ({categories.length})
        </div>
        <button
          onClick={() => setShowAddCat(!showAddCat)}
          className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 bg-transparent border-none cursor-pointer"
        >
          <Plus size={14} />
          新建分类
        </button>
      </div>

      {showAddCat && (
        <div className="border border-blue-200 bg-blue-50/50 rounded-lg p-4 space-y-3">
          <div className="text-sm font-medium text-gray-700">新建分类</div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              分类名称
            </label>
            <input
              type="text"
              value={newCatName}
              onChange={(e) => setNewCatName(e.target.value)}
              placeholder="例如：数据库操作经验"
              className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-blue-600 placeholder:text-gray-400"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              描述（可选）
            </label>
            <input
              type="text"
              value={newCatDesc}
              onChange={(e) => setNewCatDesc(e.target.value)}
              placeholder="简要说明该分类包含什么类型的经验"
              className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-blue-600 placeholder:text-gray-400"
            />
          </div>
          <div className="flex gap-2 pt-1">
            <button
              onClick={handleCreateCategory}
              disabled={saving || !newCatName.trim()}
              className="bg-blue-600 text-white border-none rounded-lg px-4 py-2 cursor-pointer text-sm font-medium hover:opacity-85 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
            >
              创建
            </button>
            <button
              onClick={() => setShowAddCat(false)}
              className="bg-gray-100 text-gray-700 border border-gray-200 rounded-lg px-4 py-2 cursor-pointer text-sm hover:border-gray-400 transition-all"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {categories.length > 0 ? (
        <div className="space-y-2">
          {categories.map((cat) => {
            const isExpanded = expanded[cat.name] ?? true;
            return (
              <div
                key={cat.name}
                className="border border-gray-200 rounded-lg p-3 hover:border-gray-300 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <button
                    onClick={() => toggleExpanded(cat.name)}
                    className="flex items-center gap-2 bg-transparent border-none cursor-pointer p-0 text-left"
                  >
                    {isExpanded ? (
                      <ChevronDown size={14} className="text-gray-400" />
                    ) : (
                      <ChevronRight size={14} className="text-gray-400" />
                    )}
                    <BookOpen size={14} className="text-emerald-500" />
                    <span className="text-sm font-medium text-gray-800">
                      {cat.name}
                    </span>
                    <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
                      {cat.documents.length} 篇
                    </span>
                  </button>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => {
                        setShowAddDoc(cat.name);
                        setNewDocName("");
                      }}
                      className="text-xs text-blue-600 hover:text-blue-800 bg-transparent border-none cursor-pointer p-1"
                      title="新建文档"
                    >
                      <Plus size={14} />
                    </button>
                    <button
                      onClick={() => handleDeleteCategory(cat.name)}
                      className="text-gray-400 hover:text-red-500 bg-transparent border-none cursor-pointer p-1 rounded hover:bg-red-50 transition-colors"
                      title="删除分类"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>

                {cat.description && (
                  <div className="text-xs text-gray-400 mt-1 ml-[30px]">
                    {cat.description}
                  </div>
                )}

                {showAddDoc === cat.name && (
                  <div className="mt-2 ml-[30px] flex items-center gap-2">
                    <input
                      type="text"
                      value={newDocName}
                      onChange={(e) => setNewDocName(e.target.value)}
                      placeholder="文档名称（如：达梦数据库备份）"
                      className="flex-1 bg-white border border-gray-200 rounded-lg p-1.5 text-xs outline-none focus:border-blue-600 placeholder:text-gray-400"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleNewDoc(cat.name);
                      }}
                    />
                    <button
                      onClick={() => handleNewDoc(cat.name)}
                      disabled={!newDocName.trim()}
                      className="text-xs bg-blue-600 text-white border-none rounded-lg px-3 py-1.5 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      创建
                    </button>
                    <button
                      onClick={() => setShowAddDoc(null)}
                      className="text-xs text-gray-500 bg-transparent border-none cursor-pointer"
                    >
                      取消
                    </button>
                  </div>
                )}

                {isExpanded && cat.documents.length > 0 && (
                  <div className="mt-2 ml-[30px] space-y-1">
                    {cat.documents.map((doc) => (
                      <div
                        key={doc.filename}
                        className="flex items-center justify-between group py-1 px-2 rounded hover:bg-gray-50"
                      >
                        <div className="flex items-center gap-2">
                          <FileText
                            size={13}
                            className="text-gray-400 flex-shrink-0"
                          />
                          <span className="text-xs text-gray-700">
                            {doc.title}
                          </span>
                          <span className="text-[10px] text-gray-400 font-mono">
                            {doc.filename}
                          </span>
                        </div>
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() =>
                              handleEditDoc(cat.name, doc.filename)
                            }
                            className="text-[11px] text-blue-600 bg-transparent border-none cursor-pointer px-1.5 py-0.5 rounded hover:bg-blue-50"
                          >
                            编辑
                          </button>
                          <button
                            onClick={() =>
                              handleDeleteDoc(cat.name, doc.filename)
                            }
                            className="text-gray-400 hover:text-red-500 bg-transparent border-none cursor-pointer p-0.5 rounded hover:bg-red-50"
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {isExpanded && cat.documents.length === 0 && (
                  <div className="mt-2 ml-[30px] text-xs text-gray-400 italic">
                    暂无文档，点击 + 新建
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        !showAddCat && (
          <div className="text-center py-6 text-gray-400">
            <BookOpen size={28} className="mx-auto mb-2 opacity-40" />
            <div className="text-sm">暂无经验文档</div>
            <div className="text-xs mt-1">
              点击「新建分类」开始组织你的经验
            </div>
          </div>
        )
      )}

      {playbooksDir && (
        <div className="bg-gray-50 rounded-lg p-3">
          <label className="block text-xs text-gray-400 mb-0.5">
            存储目录
          </label>
          <div className="text-xs text-gray-500 break-all font-mono">
            {playbooksDir}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!pbConfirmDialog}
        title={pbConfirmDialog?.title ?? ""}
        message={pbConfirmDialog?.message ?? ""}
        variant={pbConfirmDialog?.variant ?? "default"}
        confirmText={pbConfirmDialog?.confirmText ?? "确定"}
        onConfirm={() => pbConfirmDialog?.action()}
        onCancel={() => setPbConfirmDialog(null)}
      />
    </div>
  );
}

function SkillsTab() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [skillDirs, setSkillDirs] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getSkills().then((data) => {
      setSkills(data.skills);
      setSkillDirs(data.skill_dirs);
      setLoading(false);
    });
  }, []);

  if (loading) {
    return (
      <div className="p-8 text-center text-gray-400 text-sm">加载中...</div>
    );
  }

  return (
    <div className="p-5 space-y-4">
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
        <div className="text-sm text-blue-800 font-medium mb-1">
          什么是 Skill？
        </div>
        <div className="text-xs text-blue-600 leading-relaxed">
          Skill 是可复用的 AI 指令集，放置在指定目录下即可被智能体自动发现和使用。
          每个 Skill 是一个包含 <code className="bg-blue-100 px-1 rounded">SKILL.md</code> 文件的目录。
        </div>
      </div>

      <div>
        <div className="text-sm font-semibold text-gray-700 mb-2">
          Skill 搜索目录
        </div>
        {skillDirs.length > 0 ? (
          <div className="space-y-1">
            {skillDirs.map((dir, i) => (
              <div
                key={i}
                className="flex items-center gap-2 text-xs text-gray-500 bg-gray-50 rounded-lg p-2.5"
              >
                <FolderOpen size={13} className="text-gray-400 flex-shrink-0" />
                <span className="font-mono break-all">{dir}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-gray-400">
            未发现 Skill 目录。请在项目根目录创建{" "}
            <code className="bg-gray-100 px-1 rounded">.fool-code/skills/</code>{" "}
            目录，或在用户主目录创建{" "}
            <code className="bg-gray-100 px-1 rounded">.fool-code/skills/</code> 目录。
          </div>
        )}
      </div>

      <div>
        <div className="text-sm font-semibold text-gray-700 mb-2">
          已发现的 Skills ({skills.length})
        </div>
        {skills.length > 0 ? (
          <div className="space-y-2">
            {skills.map((skill) => (
              <div
                key={skill.path}
                className="border border-gray-200 rounded-lg p-3 hover:border-gray-300 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Sparkles size={14} className="text-amber-500" />
                  <span className="text-sm font-medium text-gray-800">
                    {skill.name}
                  </span>
                </div>
                {skill.description && (
                  <div className="text-xs text-gray-500 mt-1 ml-[22px]">
                    {skill.description}
                  </div>
                )}
                <div className="text-[11px] text-gray-400 mt-1 ml-[22px] font-mono break-all">
                  {skill.path}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-6 text-gray-400">
            <Sparkles size={28} className="mx-auto mb-2 opacity-40" />
            <div className="text-sm">暂未发现 Skills</div>
            <div className="text-xs mt-1">
              在 Skill 目录下创建子目录并添加 SKILL.md 文件即可
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function McpTab() {
  const [mcpSubTab, setMcpSubTab] = useState<"internal" | "manual">("internal");
  const [browserService, setBrowserService] =
    useState<BuiltinBrowserMcpResponse | null>(null);
  const [browserEnabled, setBrowserEnabled] = useState(true);
  const [browserAutoStart, setBrowserAutoStart] = useState(true);
  const [browserPort, setBrowserPort] = useState("");
  const [browserToken, setBrowserToken] = useState("");
  const [browserSaving, setBrowserSaving] = useState(false);
  const [browserRestarting, setBrowserRestarting] = useState(false);
  const [browserCopied, setBrowserCopied] = useState(false);
  const [browserExpanded, setBrowserExpanded] = useState(true);
  const [servers, setServers] = useState<McpServerInfo[]>([]);
  const [configPath, setConfigPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [addMode, setAddMode] = useState<"form" | "json">("form");
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("stdio");
  const [newCommand, setNewCommand] = useState("");
  const [newArgs, setNewArgs] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [jsonInput, setJsonInput] = useState("");
  const [jsonError, setJsonError] = useState("");
  const [saving, setSaving] = useState(false);
  const [connecting, setConnecting] = useState<Record<string, boolean>>({});
  const [toggling, setToggling] = useState<Record<string, boolean>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [connectErrors, setConnectErrors] = useState<Record<string, string>>({});
  const [editingServer, setEditingServer] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editType, setEditType] = useState("stdio");
  const [editCommand, setEditCommand] = useState("");
  const [editArgs, setEditArgs] = useState("");
  const [editUrl, setEditUrl] = useState("");

  const applyBrowserState = useCallback((browser: BuiltinBrowserMcpResponse) => {
    setBrowserService(browser);
    setBrowserEnabled(browser.enabled);
    setBrowserAutoStart(browser.auto_start);
    setBrowserPort(String(browser.bridge_port));
    setBrowserToken(browser.pairing_token);
  }, []);

  const loadServers = useCallback(async () => {
    setLoading(true);
    try {
      const [data, browser] = await Promise.all([
        api.getMcpServers(),
        api.getBuiltinBrowserMcp(),
      ]);
      setServers(data.servers);
      setConfigPath(data.config_path);
      applyBrowserState(browser);
    } finally {
      setLoading(false);
    }
  }, [applyBrowserState]);

  useEffect(() => {
    void loadServers();
  }, [loadServers]);

  const handleCopyBrowserToken = async () => {
    if (!browserToken.trim()) return;
    await navigator.clipboard.writeText(browserToken.trim());
    setBrowserCopied(true);
    window.setTimeout(() => setBrowserCopied(false), 1500);
  };

  const handleSaveBrowser = async (regenerateToken = false, enabledOverride?: boolean) => {
    setBrowserSaving(true);
    try {
      const effectiveEnabled = enabledOverride !== undefined ? enabledOverride : browserEnabled;
      const req: SaveBuiltinBrowserMcpRequest = {
        enabled: effectiveEnabled,
        auto_start: browserAutoStart,
        bridge_port: Number(browserPort) || undefined,
        pairing_token: browserToken.trim(),
        regenerate_token: regenerateToken,
      };
      const browser = await api.saveBuiltinBrowserMcp(req);
      applyBrowserState(browser);
      await loadServers();
    } finally {
      setBrowserSaving(false);
    }
  };

  const handleRestartBrowser = async () => {
    setBrowserRestarting(true);
    try {
      const browser = await api.reconnectBuiltinBrowserMcp();
      applyBrowserState(browser);
      await loadServers();
    } finally {
      setBrowserRestarting(false);
    }
  };

  const resetAddForm = () => {
    setNewName("");
    setNewCommand("");
    setNewArgs("");
    setNewUrl("");
    setNewType("stdio");
    setJsonInput("");
    setJsonError("");
    setShowAdd(false);
    setAddMode("form");
  };

  const handleAdd = async () => {
    if (!newName.trim()) return;
    setSaving(true);
    const req: SaveMcpServerRequest = {
      name: newName.trim(),
      server_type: newType,
      command: newCommand,
      args: newArgs
        .split(/\s+/)
        .map((s) => s.trim())
        .filter(Boolean),
      url: newUrl,
    };
    try {
      const data = await api.saveMcpServer(req);
      setServers(data.servers);
      resetAddForm();
    } finally {
      setSaving(false);
    }
  };

  const handleJsonImport = async () => {
    setJsonError("");
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(jsonInput.trim());
    } catch {
      setJsonError("JSON 格式不正确");
      return;
    }

    let serversToAdd: Record<string, Record<string, unknown>> = {};

    if (parsed.mcpServers && typeof parsed.mcpServers === "object") {
      serversToAdd = parsed.mcpServers as Record<string, Record<string, unknown>>;
    } else if (parsed.type && typeof parsed.type === "string") {
      const name = (parsed.name as string) || `mcp-${Date.now()}`;
      serversToAdd = { [name]: parsed };
    } else {
      const keys = Object.keys(parsed);
      const looksLikeMap = keys.length > 0 && keys.every((k) => {
        const v = parsed[k];
        return v && typeof v === "object" && !Array.isArray(v) && (v as Record<string, unknown>).type;
      });
      if (looksLikeMap) {
        serversToAdd = parsed as Record<string, Record<string, unknown>>;
      } else {
        setJsonError("无法识别 JSON 结构。支持格式：{\"name\": {\"type\":\"stdio\",...}} 或 {\"mcpServers\":{...}}");
        return;
      }
    }

    const entries = Object.entries(serversToAdd);
    if (entries.length === 0) {
      setJsonError("未找到任何 MCP 服务配置");
      return;
    }

    setSaving(true);
    try {
      let lastData: { servers: McpServerInfo[] } | null = null;
      for (const [name, cfg] of entries) {
        const serverType = String(cfg.type || "stdio");
        const req: SaveMcpServerRequest = {
          name,
          server_type: serverType,
          command: String(cfg.command || ""),
          args: Array.isArray(cfg.args) ? cfg.args.map(String) : [],
          url: String(cfg.url || ""),
        };
        lastData = await api.saveMcpServer(req);
      }
      if (lastData) setServers(lastData.servers);
      resetAddForm();
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : "导入失败");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (name: string) => {
    const data = await api.deleteMcpServer(name);
    setServers(data.servers);
    if (editingServer === name) setEditingServer(null);
  };

  const handleToggle = async (name: string, enabled: boolean) => {
    setToggling((prev) => ({ ...prev, [name]: true }));
    try {
      const data = await api.toggleMcpServer(name, enabled);
      setServers(data.servers);
    } finally {
      setToggling((prev) => ({ ...prev, [name]: false }));
    }
  };

  const handleConnect = async (name: string) => {
    setConnecting((prev) => ({ ...prev, [name]: true }));
    setConnectErrors((prev) => {
      const next = { ...prev };
      delete next[name];
      return next;
    });
    try {
      const result = await api.connectMcpServer(name);
      if (result.success) {
        await loadServers();
        setExpanded((prev) => ({ ...prev, [name]: true }));
      } else {
        setConnectErrors((prev) => ({
          ...prev,
          [name]: result.error || "连接失败",
        }));
        await loadServers();
      }
    } catch (e) {
      setConnectErrors((prev) => ({
        ...prev,
        [name]: e instanceof Error ? e.message : "连接失败",
      }));
    } finally {
      setConnecting((prev) => ({ ...prev, [name]: false }));
    }
  };

  const startEdit = (server: McpServerInfo) => {
    setEditingServer(server.name);
    setEditName(server.name);
    setEditType(server.server_type);
    setEditCommand(server.command);
    setEditArgs(server.args.join(" "));
    setEditUrl(server.url);
  };

  const handleSaveEdit = async () => {
    if (!editName.trim()) return;
    setSaving(true);
    try {
      if (editingServer && editingServer !== editName.trim()) {
        await api.deleteMcpServer(editingServer);
      }
      const req: SaveMcpServerRequest = {
        name: editName.trim(),
        server_type: editType,
        command: editCommand,
        args: editArgs.split(/\s+/).map((s) => s.trim()).filter(Boolean),
        url: editUrl,
      };
      const data = await api.saveMcpServer(req);
      setServers(data.servers);
      setEditingServer(null);
    } finally {
      setSaving(false);
    }
  };

  const toggleExpanded = (name: string) => {
    setExpanded((prev) => ({ ...prev, [name]: !prev[name] }));
  };

  const statusBadge = (status: string) => (
    <span
      className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border ${
        status === "connected"
          ? "bg-green-50 text-green-700 border-green-200"
          : status === "error"
          ? "bg-red-50 text-red-600 border-red-200"
          : status === "disabled"
          ? "bg-gray-50 text-gray-500 border-gray-200"
          : "bg-amber-50 text-amber-700 border-amber-200"
      }`}
    >
      <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${
        status === "connected" ? "bg-green-500"
        : status === "error" ? "bg-red-500"
        : status === "disabled" ? "bg-gray-300"
        : "bg-amber-400"
      }`} />
      {status === "connected" ? "已连接" : status === "error" ? "错误" : status === "disabled" ? "已禁用" : "未连接"}
    </span>
  );

  if (loading && !browserService) {
    return <div className="p-8 text-center text-gray-400 text-sm">加载中...</div>;
  }

  const connectedManualCount = servers.filter((s) => s.status === "connected").length;

  return (
    <div className="p-5 space-y-4">
      {/* 二级 Tab 切换栏 */}
      <div className="flex bg-gray-100 rounded-lg p-1 gap-1">
        <button
          onClick={() => setMcpSubTab("internal")}
          className={`flex-1 flex items-center justify-center gap-1.5 text-sm py-2 rounded-md transition-all border-none cursor-pointer ${
            mcpSubTab === "internal"
              ? "bg-white text-blue-600 font-medium shadow-sm"
              : "bg-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <Plug size={14} />
          内置服务
          {browserService && (
            <span className={`text-[10px] min-w-[18px] h-[18px] inline-flex items-center justify-center rounded-full ${
              mcpSubTab === "internal" ? "bg-blue-100 text-blue-600" : "bg-gray-200 text-gray-500"
            }`}>
              1
            </span>
          )}
        </button>
        <button
          onClick={() => setMcpSubTab("manual")}
          className={`flex-1 flex items-center justify-center gap-1.5 text-sm py-2 rounded-md transition-all border-none cursor-pointer ${
            mcpSubTab === "manual"
              ? "bg-white text-purple-600 font-medium shadow-sm"
              : "bg-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <Network size={14} />
          自定义服务
          <span className={`text-[10px] min-w-[18px] h-[18px] inline-flex items-center justify-center rounded-full ${
            mcpSubTab === "manual" ? "bg-purple-100 text-purple-600" : "bg-gray-200 text-gray-500"
          }`}>
            {servers.length}
          </span>
        </button>
      </div>

      {/* ====== 内置服务 Tab ====== */}
      {mcpSubTab === "internal" ? (
        <div className="space-y-3">
          <div className="bg-blue-50/60 border border-blue-100 rounded-lg px-3 py-2.5">
            <div className="text-xs text-blue-700/80 leading-relaxed">
              内置 MCP 服务由 Fool Code 自带，随应用启动自动管理，无需手动配置。
            </div>
          </div>

          {browserService && (
            <div className={`border rounded-xl overflow-hidden transition-colors ${
              !browserEnabled ? "border-gray-200 bg-gray-50/50 opacity-70" : "border-blue-200 bg-white"
            }`}>
              <div
                className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-blue-50/40 transition-colors"
                onClick={() => setBrowserExpanded(!browserExpanded)}
              >
                <div className="flex items-center gap-2.5">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                    browserEnabled ? "bg-blue-100" : "bg-gray-100"
                  }`}>
                    <Plug size={15} className={browserEnabled ? "text-blue-600" : "text-gray-400"} />
                  </div>
                  <div className="text-left">
                    <div className={`text-sm font-semibold ${browserEnabled ? "text-gray-800" : "text-gray-500"}`}>
                      内置浏览器服务
                    </div>
                    <div className="text-[11px] text-gray-400 mt-0.5">
                      浏览器自动化 · {browserService.tools.length} 个工具
                    </div>
                  </div>
                  {statusBadge(browserEnabled ? browserService.status : "disabled")}
                </div>
                <div className="flex items-center gap-2">
                  {/* Toggle switch */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      const next = !browserEnabled;
                      setBrowserEnabled(next);
                      void handleSaveBrowser(false, next);
                    }}
                    disabled={browserSaving}
                    className="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border-none transition-colors duration-200 focus:outline-none disabled:opacity-50"
                    style={{ background: browserEnabled ? "#4C84FF" : "#CBD5E1" }}
                    title={browserEnabled ? "禁用" : "启用"}
                  >
                    <span
                      className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                        browserEnabled ? "translate-x-[18px]" : "translate-x-[3px]"
                      }`}
                    />
                  </button>
                  {browserExpanded ? (
                    <ChevronDown size={16} className="text-gray-400" />
                  ) : (
                    <ChevronRight size={16} className="text-gray-400" />
                  )}
                </div>
              </div>

              {browserExpanded && (
                <div className="px-4 pb-4 space-y-3 border-t border-blue-100">
                  <div className="flex items-center justify-between pt-3">
                    <div className="text-xs text-blue-700/70 leading-relaxed max-w-[75%]">
                      基于 WebSocket 桥接的浏览器 MCP 服务，需配合浏览器扩展使用。
                    </div>
                    <button
                      onClick={handleRestartBrowser}
                      disabled={browserRestarting}
                      className="inline-flex items-center gap-1.5 text-xs rounded-lg border border-blue-200 bg-white px-3 py-1.5 text-blue-700 hover:bg-blue-50 disabled:opacity-50"
                    >
                      {browserRestarting ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <RotateCcw size={12} />
                      )}
                      重启服务
                    </button>
                  </div>

                  <div className="flex items-center gap-4">
                    <label className="flex items-center gap-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={browserAutoStart}
                        onChange={(e) => setBrowserAutoStart(e.target.checked)}
                        disabled={!browserEnabled}
                      />
                      启动时自动运行
                    </label>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">桥接端口</label>
                      <input
                        type="number"
                        min={1}
                        max={65535}
                        value={browserPort}
                        onChange={(e) => setBrowserPort(e.target.value)}
                        className="w-full bg-gray-50 border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-blue-600 focus:bg-white"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">配对令牌</label>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={browserToken}
                          onChange={(e) => setBrowserToken(e.target.value)}
                          className="flex-1 bg-gray-50 border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-blue-600 focus:bg-white font-mono"
                        />
                        <button
                          onClick={handleCopyBrowserToken}
                          className="w-10 h-10 inline-flex items-center justify-center rounded-lg border border-gray-200 bg-gray-50 text-gray-500 hover:text-gray-700 hover:border-gray-300"
                          title="复制令牌"
                        >
                          {browserCopied ? <Check size={14} /> : <Copy size={14} />}
                        </button>
                      </div>
                    </div>
                  </div>

                  <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 space-y-1">
                    <div className="text-xs text-gray-500">扩展 WebSocket 地址</div>
                    <div className="text-xs font-mono break-all text-gray-700">{browserService.ws_url}</div>
                    {browserService.error && (
                      <div className="text-xs text-red-500 pt-1">{browserService.error}</div>
                    )}
                  </div>

                  {browserService.tools.length > 0 && (
                    <div>
                      <button
                        onClick={() => toggleExpanded("__browser_tools__")}
                        className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 bg-transparent border-none cursor-pointer p-0 mb-1.5"
                      >
                        {expanded["__browser_tools__"] ? (
                          <ChevronDown size={12} />
                        ) : (
                          <ChevronRight size={12} />
                        )}
                        工具列表（{browserService.tools.length}）
                      </button>
                      {expanded["__browser_tools__"] && (
                        <div className="flex flex-wrap gap-1.5">
                          {browserService.tools.map((tool) => (
                            <span
                              key={tool}
                              className="inline-flex items-center text-[11px] bg-blue-50 text-blue-700 border border-blue-100 rounded-md px-2 py-0.5 font-mono"
                            >
                              {tool}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={() => handleSaveBrowser(false)}
                      disabled={browserSaving}
                      className="inline-flex items-center gap-1.5 bg-blue-600 text-white border-none rounded-lg px-4 py-2 cursor-pointer text-sm font-medium hover:opacity-85 disabled:opacity-50"
                    >
                      {browserSaving ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Save size={14} />
                      )}
                      保存
                    </button>
                    <button
                      onClick={() => handleSaveBrowser(true)}
                      disabled={browserSaving}
                      className="bg-gray-50 text-gray-700 border border-gray-200 rounded-lg px-4 py-2 cursor-pointer text-sm hover:border-gray-400"
                    >
                      重新生成令牌
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        /* ====== 自定义服务 Tab ====== */
        <div className="space-y-3">
          {/* 头部：数量统计 + 添加按钮 */}
          <div className="flex items-center justify-between">
            <div className="text-xs text-gray-400">
              共 {servers.length} 个服务
              {connectedManualCount > 0 && (
                <span className="text-green-600">，{connectedManualCount} 个已连接</span>
              )}
            </div>
            <button
              onClick={() => { setShowAdd(!showAdd); setAddMode("form"); setJsonError(""); }}
              className="flex items-center gap-1 text-xs text-purple-600 hover:text-purple-800 bg-transparent border-none cursor-pointer font-medium"
            >
              <Plus size={14} />
              添加服务
            </button>
          </div>

          {/* 添加服务表单 */}
          {showAdd && (
            <div className="border border-purple-200 bg-purple-50/40 rounded-xl p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium text-gray-700">添加 MCP 服务</div>
                <div className="flex bg-gray-100 rounded-md p-0.5 gap-0.5">
                  <button
                    onClick={() => { setAddMode("form"); setJsonError(""); }}
                    className={`text-[11px] px-2.5 py-1 rounded transition-all border-none cursor-pointer ${
                      addMode === "form"
                        ? "bg-white text-purple-600 font-medium shadow-sm"
                        : "bg-transparent text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    表单
                  </button>
                  <button
                    onClick={() => { setAddMode("json"); setJsonError(""); }}
                    className={`text-[11px] px-2.5 py-1 rounded transition-all border-none cursor-pointer ${
                      addMode === "json"
                        ? "bg-white text-purple-600 font-medium shadow-sm"
                        : "bg-transparent text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    JSON
                  </button>
                </div>
              </div>

              {addMode === "form" ? (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">名称</label>
                      <input
                        type="text"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        placeholder="my-mcp-server"
                        className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-purple-500 placeholder:text-gray-400"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">类型</label>
                      <select
                        value={newType}
                        onChange={(e) => setNewType(e.target.value)}
                        className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-purple-500 cursor-pointer appearance-none"
                      >
                        <option value="stdio">stdio（本地进程）</option>
                        <option value="sse">sse</option>
                        <option value="http">http</option>
                      </select>
                    </div>
                  </div>

                  {newType === "stdio" ? (
                    <>
                      <div>
                        <label className="block text-xs text-gray-500 mb-1">命令</label>
                        <input
                          type="text"
                          value={newCommand}
                          onChange={(e) => setNewCommand(e.target.value)}
                          placeholder="如 npx、python、node"
                          className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-purple-500 placeholder:text-gray-400"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-gray-500 mb-1">参数（空格分隔）</label>
                        <input
                          type="text"
                          value={newArgs}
                          onChange={(e) => setNewArgs(e.target.value)}
                          placeholder="如 -m your.module"
                          className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-purple-500 placeholder:text-gray-400"
                        />
                      </div>
                    </>
                  ) : (
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">地址</label>
                      <input
                        type="text"
                        value={newUrl}
                        onChange={(e) => setNewUrl(e.target.value)}
                        placeholder="http://localhost:3000/mcp"
                        className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-purple-500 placeholder:text-gray-400"
                      />
                    </div>
                  )}

                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={handleAdd}
                      disabled={saving || !newName.trim()}
                      className="bg-purple-600 text-white border-none rounded-lg px-4 py-2 cursor-pointer text-sm font-medium hover:opacity-85 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {saving ? "保存中..." : "保存"}
                    </button>
                    <button
                      onClick={resetAddForm}
                      className="bg-gray-100 text-gray-700 border border-gray-200 rounded-lg px-4 py-2 cursor-pointer text-sm hover:border-gray-400 transition-all"
                    >
                      取消
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">
                      粘贴 JSON 配置（支持 Cursor/Claude Desktop 格式）
                    </label>
                    <textarea
                      value={jsonInput}
                      onChange={(e) => { setJsonInput(e.target.value); setJsonError(""); }}
                      rows={8}
                      placeholder={`{\n  "my-server": {\n    "type": "stdio",\n    "command": "npx",\n    "args": ["-y", "@some/mcp-server"]\n  }\n}`}
                      className="w-full bg-white border border-gray-200 rounded-lg p-3 text-[12px] font-mono leading-5 outline-none focus:border-purple-500 placeholder:text-gray-400 resize-y"
                    />
                    {jsonError && (
                      <div className="text-xs text-red-500 mt-1">{jsonError}</div>
                    )}
                  </div>
                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={handleJsonImport}
                      disabled={saving || !jsonInput.trim()}
                      className="bg-purple-600 text-white border-none rounded-lg px-4 py-2 cursor-pointer text-sm font-medium hover:opacity-85 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {saving ? "导入中..." : "解析并导入"}
                    </button>
                    <button
                      onClick={resetAddForm}
                      className="bg-gray-100 text-gray-700 border border-gray-200 rounded-lg px-4 py-2 cursor-pointer text-sm hover:border-gray-400 transition-all"
                    >
                      取消
                    </button>
                  </div>
                </>
              )}
            </div>
          )}

          {/* 服务列表 */}
          {servers.length > 0 ? (
            <div className="space-y-2">
              {servers.map((server) => {
                const isConnecting = connecting[server.name] || false;
                const isToggling = toggling[server.name] || false;
                const isExpanded = expanded[server.name] || false;
                const isEditing = editingServer === server.name;
                const error = connectErrors[server.name] || server.error;
                const isConnected = server.status === "connected";
                const isDisabled = !server.enabled;
                const hasTools = server.tools.length > 0;

                return (
                  <div
                    key={server.name}
                    className={`border rounded-xl overflow-hidden transition-colors ${
                      isDisabled
                        ? "border-gray-200 bg-gray-50/50 opacity-70"
                        : isConnected
                        ? "border-green-200 bg-white"
                        : server.status === "error"
                        ? "border-red-200 bg-white"
                        : "border-gray-200 bg-white"
                    }`}
                  >
                    {/* 卡片头部 */}
                    <div
                      className={`flex items-center justify-between px-3.5 py-3 cursor-pointer transition-colors ${
                        isDisabled
                          ? "hover:bg-gray-100/60"
                          : isConnected
                          ? "hover:bg-green-50/40"
                          : server.status === "error"
                          ? "hover:bg-red-50/40"
                          : "hover:bg-gray-50"
                      }`}
                      onClick={() => toggleExpanded(server.name)}
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                          isDisabled
                            ? "bg-gray-100"
                            : isConnected
                            ? "bg-green-100"
                            : server.status === "error"
                            ? "bg-red-100"
                            : "bg-gray-100"
                        }`}>
                          <Network size={14} className={
                            isDisabled
                              ? "text-gray-400"
                              : isConnected
                              ? "text-green-600"
                              : server.status === "error"
                              ? "text-red-500"
                              : "text-gray-400"
                          } />
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className={`text-sm font-medium truncate ${isDisabled ? "text-gray-500" : "text-gray-800"}`}>
                              {server.name}
                            </span>
                            <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded flex-shrink-0">
                              {server.server_type}
                            </span>
                          </div>
                          <div className="flex items-center gap-2 mt-0.5">
                            {statusBadge(server.status)}
                            {isConnected && hasTools && (
                              <span className="text-[11px] text-green-600">
                                {server.tools.length} 个工具
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        {/* Toggle switch */}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleToggle(server.name, !server.enabled);
                          }}
                          disabled={isToggling}
                          className="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border-none transition-colors duration-200 focus:outline-none disabled:opacity-50"
                          style={{ background: server.enabled ? "#4C84FF" : "#CBD5E1" }}
                          title={server.enabled ? "禁用" : "启用"}
                        >
                          <span
                            className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                              server.enabled ? "translate-x-[18px]" : "translate-x-[3px]"
                            }`}
                          />
                        </button>

                        {!isDisabled && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleConnect(server.name);
                            }}
                            disabled={isConnecting}
                            className={`flex items-center gap-1 text-xs border-none rounded-lg px-2.5 py-1.5 cursor-pointer font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
                              isConnected
                                ? "bg-gray-100 text-gray-600 hover:bg-gray-200"
                                : "bg-purple-600 text-white hover:opacity-85"
                            }`}
                          >
                            {isConnecting ? (
                              <>
                                <Loader2 size={12} className="animate-spin" />
                                连接中
                              </>
                            ) : isConnected ? (
                              <>
                                <RefreshCw size={12} />
                                重连
                              </>
                            ) : (
                              <>
                                <Plug size={12} />
                                连接
                              </>
                            )}
                          </button>
                        )}

                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDelete(server.name);
                          }}
                          className="text-gray-400 hover:text-red-500 bg-transparent border-none cursor-pointer p-1 rounded hover:bg-red-50 transition-colors"
                          title="删除"
                        >
                          <Trash2 size={14} />
                        </button>
                        {isExpanded ? (
                          <ChevronDown size={16} className="text-gray-400" />
                        ) : (
                          <ChevronRight size={16} className="text-gray-400" />
                        )}
                      </div>
                    </div>

                    {/* 展开内容 */}
                    {isExpanded && (
                      <div className="px-3.5 pb-3 border-t border-gray-100 pt-2.5 space-y-2">
                        {isEditing ? (
                          <div className="space-y-2.5">
                            <div className="grid grid-cols-2 gap-2.5">
                              <div>
                                <label className="block text-xs text-gray-500 mb-1">名称</label>
                                <input
                                  type="text"
                                  value={editName}
                                  onChange={(e) => setEditName(e.target.value)}
                                  className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-purple-500"
                                />
                              </div>
                              <div>
                                <label className="block text-xs text-gray-500 mb-1">类型</label>
                                <select
                                  value={editType}
                                  onChange={(e) => setEditType(e.target.value)}
                                  className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-purple-500 cursor-pointer appearance-none"
                                >
                                  <option value="stdio">stdio</option>
                                  <option value="sse">sse</option>
                                  <option value="http">http</option>
                                </select>
                              </div>
                            </div>
                            {editType === "stdio" ? (
                              <>
                                <div>
                                  <label className="block text-xs text-gray-500 mb-1">命令</label>
                                  <input
                                    type="text"
                                    value={editCommand}
                                    onChange={(e) => setEditCommand(e.target.value)}
                                    className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-purple-500"
                                  />
                                </div>
                                <div>
                                  <label className="block text-xs text-gray-500 mb-1">参数</label>
                                  <input
                                    type="text"
                                    value={editArgs}
                                    onChange={(e) => setEditArgs(e.target.value)}
                                    className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-purple-500"
                                  />
                                </div>
                              </>
                            ) : (
                              <div>
                                <label className="block text-xs text-gray-500 mb-1">地址</label>
                                <input
                                  type="text"
                                  value={editUrl}
                                  onChange={(e) => setEditUrl(e.target.value)}
                                  className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-purple-500"
                                />
                              </div>
                            )}
                            <div className="flex gap-2 pt-1">
                              <button
                                onClick={handleSaveEdit}
                                disabled={saving || !editName.trim()}
                                className="bg-purple-600 text-white border-none rounded-lg px-3 py-1.5 cursor-pointer text-xs font-medium hover:opacity-85 disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                {saving ? "保存中..." : "保存修改"}
                              </button>
                              <button
                                onClick={() => setEditingServer(null)}
                                className="bg-gray-100 text-gray-700 border border-gray-200 rounded-lg px-3 py-1.5 cursor-pointer text-xs hover:border-gray-400"
                              >
                                取消
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <div className="flex items-center justify-between">
                              <div className="text-xs text-gray-500 font-mono break-all bg-gray-50 rounded-lg px-2.5 py-2 flex-1">
                                {server.server_type === "stdio"
                                  ? `${server.command} ${server.args.join(" ")}`
                                  : server.url}
                              </div>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  startEdit(server);
                                }}
                                className="ml-2 flex-shrink-0 text-xs text-purple-600 hover:text-purple-800 bg-transparent border border-purple-200 rounded-lg px-2.5 py-1.5 cursor-pointer hover:bg-purple-50 transition-colors"
                              >
                                编辑
                              </button>
                            </div>

                            {error && (
                              <div className="text-xs text-red-500 bg-red-50 border border-red-100 rounded-lg px-2.5 py-1.5">
                                {error}
                              </div>
                            )}

                            {hasTools && (
                              <div className="flex flex-wrap gap-1.5 pt-1">
                                {server.tools.map((tool) => (
                                  <span
                                    key={tool}
                                    className="inline-flex items-center text-[11px] bg-purple-50 text-purple-700 border border-purple-100 rounded-md px-2 py-0.5 font-mono"
                                  >
                                    {tool}
                                  </span>
                                ))}
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            !showAdd && (
              <div className="text-center py-8 text-gray-400">
                <Network size={28} className="mx-auto mb-2 opacity-40" />
                <div className="text-sm">暂无自定义 MCP 服务</div>
                <div className="text-xs mt-1">点击上方「添加服务」进行配置</div>
              </div>
            )
          )}

          {configPath && (
            <div className="bg-gray-50 rounded-lg p-3">
              <label className="block text-xs text-gray-400 mb-0.5">配置路径</label>
              <div className="text-xs text-gray-500 break-all font-mono">{configPath}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function WorkspaceTab() {
  const [workspace, setWorkspace] = useState<WorkspaceResponse | null>(null);
  const [newRoot, setNewRoot] = useState("");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{
    text: string;
    color: string;
  } | null>(null);

  useEffect(() => {
    api.getWorkspace().then((data) => {
      setWorkspace(data);
      setNewRoot(data.workspace_root);
    });
  }, []);

  const handleSave = async () => {
    if (!newRoot.trim()) return;
    setSaving(true);
    setStatus(null);
    try {
      const data = await api.setWorkspace(newRoot.trim());
      setWorkspace(data);
      setNewRoot(data.workspace_root);
      setEditing(false);
      setStatus({
        text: "Workspace root updated.",
        color: "text-green-600",
      });
    } catch (e) {
      setStatus({
        text: `Update failed: ${e instanceof Error ? e.message : "Unknown error"}`,
        color: "text-red-600",
      });
    } finally {
      setSaving(false);
    }
  };

  if (!workspace) {
    return (
      <div className="p-8 text-center text-gray-400 text-sm">Loading...</div>
    );
  }

  const dirs = [
    {
      label: "App Data Root",
      path: workspace.app_data_root,
      desc: "Stable per-user storage for Fool Code data",
    },
    {
      label: "Config",
      path: workspace.config_path,
      desc: "settings.json for models, MCP, and workspace preferences",
    },
    {
      label: "Sessions",
      path: workspace.sessions_path,
      desc: "Conversation history storage",
    },
    {
      label: "Skills",
      path: workspace.skills_path,
      desc: "Default skill directory",
    },
  ];

  return (
    <div className="p-5 space-y-4">
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
        <div className="text-sm text-blue-800 font-medium mb-1">Storage Model</div>
        <div className="text-xs text-blue-600 leading-relaxed">
          Fool Code now keeps config, sessions, and skills in a stable user-level
          folder. The workspace root below only controls the default project
          context and relative paths.
        </div>
      </div>

      <div>
        <label className="block text-sm font-semibold text-gray-700 mb-1.5">
          Workspace Root
        </label>
        {!editing ? (
          <div className="flex items-center gap-2">
            <div className="flex-1 bg-gray-50 border border-gray-200 rounded-lg p-2.5 text-sm text-gray-700 font-mono break-all">
              {workspace.workspace_root}
            </div>
            <button
              onClick={() => setEditing(true)}
              className="text-xs text-blue-600 hover:text-blue-800 bg-transparent border border-blue-200 rounded-lg px-3 py-2 cursor-pointer whitespace-nowrap hover:bg-blue-50 transition-colors"
            >
              Edit
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <input
              type="text"
              value={newRoot}
              onChange={(e) => setNewRoot(e.target.value)}
              placeholder="Enter a workspace path"
              className="w-full bg-gray-50 border border-gray-200 rounded-lg p-2.5 text-sm outline-none focus:border-blue-600 placeholder:text-gray-400 font-mono"
            />
            <div className="flex gap-2">
              <button
                onClick={handleSave}
                disabled={saving || !newRoot.trim()}
                className="bg-blue-600 text-white border-none rounded-lg px-4 py-2 cursor-pointer text-sm font-medium hover:opacity-85 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {saving ? "Saving..." : "Save"}
              </button>
              <button
                onClick={() => {
                  setEditing(false);
                  setNewRoot(workspace.workspace_root);
                  setStatus(null);
                }}
                className="bg-gray-100 text-gray-700 border border-gray-200 rounded-lg px-4 py-2 cursor-pointer text-sm hover:border-gray-400 transition-all"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
        {status && (
          <div className={`text-xs mt-1.5 ${status.color}`}>{status.text}</div>
        )}
      </div>

      <div>
        <div className="text-sm font-semibold text-gray-700 mb-2">Paths</div>
        <div className="space-y-2">
          {dirs.map((d) => (
            <div
              key={d.label}
              className="border border-gray-200 rounded-lg p-3"
            >
              <div className="flex items-center gap-2 mb-0.5">
                <FolderOpen
                  size={14}
                  className="text-blue-500 flex-shrink-0"
                />
                <span className="text-sm font-medium text-gray-800">
                  {d.label}
                </span>
              </div>
              <div className="text-[11px] text-gray-400 ml-[22px]">
                {d.desc}
              </div>
              <div className="text-xs text-gray-500 ml-[22px] mt-0.5 font-mono break-all">
                {d.path}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

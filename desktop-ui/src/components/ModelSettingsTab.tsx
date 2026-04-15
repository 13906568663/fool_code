import { useState, useEffect, useCallback, useMemo } from "react";
import {
  ChevronDown,
  RefreshCw,
  Loader2,
  Plus,
  Trash2,
  Check,
} from "lucide-react";
import type { SettingsResponse, SaveSettingsRequest, ModelInfo } from "../types";
import * as api from "../services/api";

interface EditableProviderRow {
  id: string;
  label: string;
  provider: string;
  apiKey: string;
  apiKeyMasked: string;
  baseUrl: string;
  model: string;
  savedModels: string[];
  /** false = 尚未写入 settings，拉取列表时不要带 provider_id */
  persisted: boolean;
}

function newClientRowId(): string {
  const u =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID().replace(/-/g, "").slice(0, 12)
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  return `p-${u}`;
}

function rowFromApi(r: NonNullable<SettingsResponse["model_providers"]>[number]): EditableProviderRow {
  return {
    id: r.id,
    label: r.label || r.id,
    provider: r.provider || "openai",
    apiKey: "",
    apiKeyMasked: r.api_key_masked || "",
    baseUrl: r.base_url || "",
    model: r.model || "qwen3.5-plus",
    savedModels: r.saved_models ?? [],
    persisted: true,
  };
}

export default function ModelSettingsTab({
  onClose,
  onModelChange,
}: {
  onClose: () => void;
  onModelChange?: (model: string) => void;
}) {
  const [rows, setRows] = useState<EditableProviderRow[]>([]);
  const [defaultProviderId, setDefaultProviderId] = useState("");
  const [presetByProvider, setPresetByProvider] = useState<Record<string, ModelInfo[]>>({});
  const [discoveredById, setDiscoveredById] = useState<Record<string, ModelInfo[]>>({});
  const [discoverLoadingId, setDiscoverLoadingId] = useState<string | null>(null);
  const [discoverErrorById, setDiscoverErrorById] = useState<Record<string, string | null>>({});
  const [customSavedInputById, setCustomSavedInputById] = useState<Record<string, string>>({});
  const [configPath, setConfigPath] = useState("");
  const [saveStatus, setSaveStatus] = useState<{ text: string; color: string } | null>(null);

  const providerKeys = useMemo(
    () => [...new Set(rows.map((r) => r.provider))].sort().join("|"),
    [rows]
  );

  useEffect(() => {
    const providers = [...new Set(rows.map((r) => r.provider))];
    for (const p of providers) {
      api.getModels(p).then((data) => {
        setPresetByProvider((prev) => (prev[p] ? prev : { ...prev, [p]: data.models }));
      });
    }
  }, [providerKeys, rows.length]);

  const reloadSettings = useCallback(() => {
    api.getSettings().then((data: SettingsResponse) => {
      const list = data.model_providers;
      if (list && list.length > 0) {
        const mapped = list.map(rowFromApi);
        setRows(mapped);
        const dpid = data.default_provider_id?.trim();
        setDefaultProviderId(
          dpid && mapped.some((m) => m.id === dpid) ? dpid : mapped[0].id
        );
      } else {
        const nid = newClientRowId();
        setRows([
          {
            id: nid,
            label: "默认",
            provider: data.provider || "openai",
            apiKey: "",
            apiKeyMasked: data.api_key_masked || "",
            baseUrl: data.base_url || "",
            model: data.model || "qwen3.5-plus",
            savedModels: data.saved_models ?? [],
            persisted: false,
          },
        ]);
        setDefaultProviderId(nid);
      }
      setConfigPath(data.config_path || "");
      setSaveStatus(null);
      setDiscoveredById({});
      setDiscoverErrorById({});
    });
  }, []);

  useEffect(() => {
    reloadSettings();
  }, [reloadSettings]);

  const listForRow = useCallback(
    (row: EditableProviderRow) => {
      const discovered = discoveredById[row.id] ?? [];
      if (row.provider === "openai" && discovered.length > 0) return discovered;
      return presetByProvider[row.provider] ?? [];
    },
    [discoveredById, presetByProvider]
  );

  const handleDiscoverRow = useCallback(
    async (row: EditableProviderRow) => {
      if (row.provider !== "openai") {
        setDiscoverErrorById((prev) => ({
          ...prev,
          [row.id]: "仅 OpenAI 兼容接口支持拉取模型列表",
        }));
        return;
      }
      setDiscoverLoadingId(row.id);
      setDiscoverErrorById((prev) => ({ ...prev, [row.id]: null }));
      try {
        const res = await api.discoverModels({
          api_key: row.apiKey,
          base_url: row.baseUrl,
          provider_id: row.persisted ? row.id : undefined,
        });
        if (res.error) {
          setDiscoverErrorById((prev) => ({ ...prev, [row.id]: res.error ?? null }));
          setDiscoveredById((prev) => ({ ...prev, [row.id]: [] }));
        } else {
          setDiscoveredById((prev) => ({ ...prev, [row.id]: res.models }));
          if (res.models.length > 0) {
            setSaveStatus({
              text: `「${row.label}」已获取 ${res.models.length} 个模型`,
              color: "text-green-600",
            });
          }
        }
      } catch (e) {
        setDiscoverErrorById((prev) => ({
          ...prev,
          [row.id]: e instanceof Error ? e.message : "拉取失败",
        }));
        setDiscoveredById((prev) => ({ ...prev, [row.id]: [] }));
      } finally {
        setDiscoverLoadingId(null);
      }
    },
    []
  );

  const updateRow = useCallback((id: string, patch: Partial<EditableProviderRow>) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }, []);

  const addRow = useCallback(() => {
    const nid = newClientRowId();
    setRows((prev) => [
      ...prev,
      {
        id: nid,
        label: `提供商 ${prev.length + 1}`,
        provider: "openai",
        apiKey: "",
        apiKeyMasked: "",
        baseUrl: "",
        model: "qwen3.5-plus",
        savedModels: [],
        persisted: false,
      },
    ]);
    setDefaultProviderId((d) => d || nid);
  }, []);

  const removeRow = useCallback(
    (id: string) => {
      setRows((prev) => {
        if (prev.length <= 1) return prev;
        const next = prev.filter((r) => r.id !== id);
        setDefaultProviderId((d) => {
          if (d !== id) return d;
          return next[0]?.id ?? "";
        });
        return next;
      });
    },
    []
  );

  const addSaved = useCallback((rowId: string, mid: string) => {
    const t = mid.trim();
    if (!t) return;
    setRows((prev) =>
      prev.map((r) =>
        r.id === rowId && !r.savedModels.includes(t)
          ? { ...r, savedModels: [...r.savedModels, t] }
          : r
      )
    );
  }, []);

  const removeSaved = useCallback((rowId: string, mid: string) => {
    setRows((prev) =>
      prev.map((r) =>
        r.id === rowId
          ? { ...r, savedModels: r.savedModels.filter((x) => x !== mid) }
          : r
      )
    );
  }, []);

  const handleSave = useCallback(async () => {
    const hasTypedKey = rows.some((r) => r.apiKey.trim());
    const hasStoredKey = rows.some((r) => (r.apiKeyMasked || "").length > 0);
    if (!hasTypedKey && !hasStoredKey) {
      setSaveStatus({ text: "请至少为一个提供商配置 API Key", color: "text-red-600" });
      return;
    }

    let defId = defaultProviderId;
    if (!defId || !rows.some((r) => r.id === defId)) {
      defId = rows[0]?.id ?? "";
    }

    const body: SaveSettingsRequest = {
      provider: rows[0]?.provider ?? "openai",
      api_key: "",
      base_url: "",
      model: rows[0]?.model ?? "",
      saved_models: [],
      default_provider_id: defId,
      model_providers: rows.map((r) => ({
        id: r.id,
        label: r.label,
        provider: r.provider,
        api_key: r.apiKey,
        base_url: r.baseUrl,
        model: r.model || "qwen3.5-plus",
        saved_models: r.savedModels,
      })),
    };

    try {
      const result = await api.saveSettings(body);
      setSaveStatus({ text: "已保存", color: "text-green-600" });
      onModelChange?.(result.model);
      const list = result.model_providers;
      if (list && list.length > 0) {
        const mapped = list.map(rowFromApi);
        setRows(mapped);
        const dpid = result.default_provider_id?.trim();
        setDefaultProviderId(
          dpid && mapped.some((m) => m.id === dpid) ? dpid : mapped[0].id
        );
      }
    } catch (e) {
      setSaveStatus({
        text: `保存失败: ${e instanceof Error ? e.message : "未知错误"}`,
        color: "text-red-600",
      });
    }
  }, [rows, defaultProviderId, onModelChange]);

  return (
    <div className="flex flex-col h-full">
      <div className="p-5 space-y-4 flex-1 overflow-y-auto">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-gray-500 leading-relaxed">
            可配置多个模型提供商；勾选「工作区默认」的提供商及其默认模型，将作为新对话的默认调用目标。
          </p>
          <button
            type="button"
            onClick={addRow}
            className="flex items-center gap-1 text-xs bg-gray-100 border border-gray-200 rounded-lg px-2.5 py-1.5 cursor-pointer hover:bg-gray-200 shrink-0"
          >
            <Plus size={14} />
            添加提供商
          </button>
        </div>

        {rows.map((row) => {
          const list = listForRow(row);
          const isCustom =
            row.model !== "" && !list.some((m) => m.id === row.model);
          const discoverErr = discoverErrorById[row.id];
          const disc = discoveredById[row.id] ?? [];
          const loading = discoverLoadingId === row.id;
          const isDefault = defaultProviderId === row.id;

          return (
            <div
              key={row.id}
              className={`border rounded-xl p-4 space-y-3 ${
                isDefault
                  ? "border-blue-300 bg-blue-50/30 ring-1 ring-blue-200"
                  : "border-gray-200 bg-gray-50/50"
              }`}
            >
              {isDefault && (
                <div className="flex items-center gap-2 bg-blue-600 text-white rounded-lg px-3 py-2 -mx-1 -mt-1 mb-1">
                  <Check size={14} className="shrink-0" />
                  <span className="text-xs font-medium">当前生效</span>
                  <span className="text-xs opacity-90 ml-1">
                    {row.label} / {row.model || "未选择模型"}
                  </span>
                </div>
              )}
              <div className="flex items-center gap-3 flex-wrap">
                <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer">
                  <input
                    type="radio"
                    name="defaultProvider"
                    checked={defaultProviderId === row.id}
                    onChange={() => setDefaultProviderId(row.id)}
                    className="cursor-pointer"
                  />
                  工作区默认
                </label>
                <input
                  type="text"
                  value={row.label}
                  onChange={(e) => updateRow(row.id, { label: e.target.value })}
                  placeholder="显示名称"
                  className="flex-1 min-w-[120px] bg-white border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm outline-none focus:border-blue-600"
                />
                {rows.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeRow(row.id)}
                    className="text-gray-400 hover:text-red-500 bg-transparent border-none cursor-pointer p-1"
                    title="删除此提供商"
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">
                  AI 提供商类型
                </label>
                <select
                  value={row.provider}
                  onChange={(e) => updateRow(row.id, { provider: e.target.value })}
                  className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-blue-600 cursor-pointer appearance-none"
                >
                  <option value="openai">OpenAI 兼容（通义千问/DeepSeek/Ollama）</option>
                  <option value="anthropic">Anthropic（Claude）</option>
                  <option value="xai">xAI（Grok）</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">
                  API Key
                </label>
                <input
                  type="password"
                  value={row.apiKey}
                  onChange={(e) => updateRow(row.id, { apiKey: e.target.value })}
                  placeholder="输入 API Key"
                  className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-blue-600"
                />
                <div className="text-[11px] text-gray-400 mt-0.5">
                  已保存: {row.apiKeyMasked || "未配置"}
                </div>
              </div>

              {row.provider === "openai" && (
                <div>
                  <label className="block text-xs font-semibold text-gray-600 mb-1">
                    API Base URL
                  </label>
                  <input
                    type="text"
                    value={row.baseUrl}
                    onChange={(e) => updateRow(row.id, { baseUrl: e.target.value })}
                    placeholder="https://…/v1"
                    className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-blue-600"
                  />
                  <div className="mt-2 flex items-center gap-2 flex-wrap">
                    <button
                      type="button"
                      onClick={() => handleDiscoverRow(row)}
                      disabled={loading}
                      className="text-xs bg-purple-600 text-white border-none rounded-lg px-3 py-1.5 cursor-pointer hover:opacity-90 disabled:opacity-50 flex items-center gap-1"
                    >
                      {loading ? (
                        <>
                          <Loader2 size={12} className="animate-spin" />
                          拉取中…
                        </>
                      ) : (
                        <>
                          <RefreshCw size={12} />
                          拉取模型列表
                        </>
                      )}
                    </button>
                  </div>
                  {discoverErr && (
                    <div className="text-[11px] text-red-500 mt-1">{discoverErr}</div>
                  )}
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">
                  此提供商默认模型
                </label>
                {!isCustom ? (
                  <div className="relative">
                    <select
                      value={row.model}
                      onChange={(e) => {
                        if (e.target.value === "__custom__") {
                          updateRow(row.id, { model: "" });
                        } else {
                          updateRow(row.id, { model: e.target.value });
                        }
                      }}
                      className="w-full bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-blue-600 cursor-pointer appearance-none pr-8"
                    >
                      <option value="">请选择模型...</option>
                      {list.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name} ({m.id})
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
                      value={row.model}
                      onChange={(e) => updateRow(row.id, { model: e.target.value })}
                      placeholder="模型 ID"
                      className="flex-1 bg-white border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-blue-600 font-mono"
                    />
                    <button
                      type="button"
                      onClick={() => updateRow(row.id, { model: "" })}
                      className="text-xs text-blue-600 bg-transparent border-none cursor-pointer whitespace-nowrap"
                    >
                      选预设
                    </button>
                  </div>
                )}
              </div>

              {row.provider === "openai" && (
                <div>
                  <label className="block text-xs font-semibold text-gray-600 mb-1">
                    常用模型（仅本提供商）
                  </label>
                  <div className="flex flex-wrap gap-1.5 mb-2 min-h-[24px]">
                    {row.savedModels.length === 0 ? (
                      <span className="text-[11px] text-gray-400">暂无</span>
                    ) : (
                      row.savedModels.map((id) => (
                        <span
                          key={id}
                          className="inline-flex items-center gap-1 text-[11px] bg-white border border-gray-200 rounded-full px-2 py-0.5"
                        >
                          <span className="font-mono max-w-[140px] truncate" title={id}>
                            {id}
                          </span>
                          <button
                            type="button"
                            onClick={() => removeSaved(row.id, id)}
                            className="text-gray-400 hover:text-red-500 bg-transparent border-none cursor-pointer p-0"
                          >
                            ×
                          </button>
                        </span>
                      ))
                    )}
                  </div>
                  {disc.length > 0 && (
                    <div className="max-h-24 overflow-y-auto border border-gray-100 rounded-lg p-2 space-y-0.5 mb-2 bg-white">
                      {disc.slice(0, 40).map((m) => (
                        <div
                          key={m.id}
                          className="flex items-center justify-between text-[11px] gap-2"
                        >
                          <span className="truncate font-mono text-gray-700">{m.id}</span>
                          <button
                            type="button"
                            onClick={() => addSaved(row.id, m.id)}
                            disabled={row.savedModels.includes(m.id)}
                            className="text-purple-600 bg-transparent border-none cursor-pointer shrink-0 disabled:text-gray-300"
                          >
                            {row.savedModels.includes(m.id) ? "已添加" : "+常用"}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={customSavedInputById[row.id] ?? ""}
                      onChange={(e) =>
                        setCustomSavedInputById((prev) => ({
                          ...prev,
                          [row.id]: e.target.value,
                        }))
                      }
                      placeholder="手动输入模型 ID"
                      className="flex-1 bg-white border border-gray-200 rounded-lg px-2 py-1 text-[11px] outline-none font-mono"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        addSaved(row.id, customSavedInputById[row.id] ?? "");
                        setCustomSavedInputById((prev) => ({ ...prev, [row.id]: "" }));
                      }}
                      className="text-[11px] bg-gray-200 border-none rounded-lg px-2 py-1 cursor-pointer"
                    >
                      添加
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {configPath && (
          <div className="bg-gray-50 rounded-lg p-3">
            <label className="block text-xs text-gray-400 mb-0.5">配置文件路径</label>
            <div className="text-xs text-gray-500 break-all font-mono">{configPath}</div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 p-4 border-t border-gray-200 flex-shrink-0">
        <button
          onClick={onClose}
          className="bg-gray-100 text-gray-700 border border-gray-200 rounded-lg px-5 py-2.5 cursor-pointer text-sm hover:border-gray-400"
        >
          取消
        </button>
        <button
          onClick={handleSave}
          className="bg-blue-600 text-white border-none rounded-lg px-5 py-2.5 cursor-pointer text-sm font-semibold hover:opacity-85"
        >
          保存设置
        </button>
        {saveStatus && (
          <span className={`text-xs ml-2 ${saveStatus.color}`}>{saveStatus.text}</span>
        )}
      </div>
    </div>
  );
}

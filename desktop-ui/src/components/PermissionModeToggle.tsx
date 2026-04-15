import { useCallback, useEffect, useMemo, useState } from "react";
import {
  LoaderCircle,
  ShieldAlert,
  ShieldCheck,
  ShieldEllipsis,
  Zap,
} from "lucide-react";
import type { PermissionMode } from "../types";
import * as api from "../services/api";

type ModeOption = {
  mode: PermissionMode;
  title: string;
  hint: string;
  icon: typeof ShieldCheck;
};

const OPTIONS: ModeOption[] = [
  {
    mode: "default",
    title: "默认权限",
    hint: "写入前确认",
    icon: ShieldCheck,
  },
  {
    mode: "danger-full-access",
    title: "完全访问",
    hint: "直接执行",
    icon: Zap,
  },
];

function describeMode(mode: PermissionMode): string {
  switch (mode) {
    case "default":
      return "需要确认";
    case "danger-full-access":
      return "直接执行";
    case "read-only":
      return "只读模式";
    case "workspace-write":
      return "工作区写入";
    case "dont-ask":
      return "不再询问";
    default:
      return "已加载";
  }
}

export default function PermissionModeToggle() {
  const [mode, setMode] = useState<PermissionMode>("danger-full-access");
  const [loading, setLoading] = useState(true);
  const [savingMode, setSavingMode] = useState<PermissionMode | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api
      .getPermissionMode()
      .then((response) => {
        if (!active) return;
        setMode(response.mode);
      })
      .catch(() => {
        if (!active) return;
        setError("权限模式读取失败");
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const description = useMemo(() => describeMode(mode), [mode]);
  const supportedMode = OPTIONS.some((option) => option.mode === mode);

  const handleSelect = useCallback(
    async (nextMode: PermissionMode) => {
      if (loading || savingMode || nextMode === mode) return;
      setSavingMode(nextMode);
      setError("");
      try {
        const response = await api.setPermissionMode(nextMode);
        setMode(response.mode);
      } catch (err) {
        setError(err instanceof Error ? err.message : "权限模式更新失败");
      } finally {
        setSavingMode(null);
      }
    },
    [loading, mode, savingMode]
  );

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="inline-flex flex-wrap items-center gap-2 rounded-full border border-[#E7ECF3] bg-white/95 p-1.5 shadow-[0_14px_36px_rgba(31,42,68,0.06)] backdrop-blur-sm">
        <div className="flex min-w-0 items-center gap-2 rounded-full px-2.5 py-1.5 text-slate-600">
          <span className="inline-flex size-8 items-center justify-center rounded-full bg-[#F5F7FB] text-slate-400">
            <ShieldEllipsis size={15} />
          </span>
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Permission
            </div>
            <div className="truncate text-xs font-medium text-slate-600">
              {description}
            </div>
          </div>
        </div>

        <div className="inline-flex items-center rounded-full border border-[#E7ECF3] bg-[#FCFDFF] p-1">
          {OPTIONS.map((option) => {
            const selected = option.mode === mode;
            const saving = savingMode === option.mode;
            const Icon = option.icon;

            return (
              <button
                key={option.mode}
                type="button"
                onClick={() => void handleSelect(option.mode)}
                disabled={loading || !!savingMode}
                title={`${option.title} · ${option.hint}`}
                className={`inline-flex h-10 items-center gap-2 rounded-full px-3.5 text-sm transition-all disabled:cursor-not-allowed disabled:opacity-60 ${
                  selected
                    ? "border border-[#DCE7FF] bg-[#EFF4FF] text-[#3767D6] shadow-[0_4px_14px_rgba(76,132,255,0.12)]"
                    : "border border-transparent bg-transparent text-slate-500 hover:bg-white hover:text-slate-700"
                }`}
              >
                <span
                  className={`inline-flex size-6 items-center justify-center rounded-full ${
                    selected
                      ? "bg-white text-[#4C84FF]"
                      : "bg-[#F3F6FB] text-slate-400"
                  }`}
                >
                  {saving ? (
                    <LoaderCircle size={13} className="animate-spin" />
                  ) : (
                    <Icon size={13} />
                  )}
                </span>
                <span className="font-medium">{option.title}</span>
              </button>
            );
          })}
        </div>
      </div>

      {!supportedMode && !loading && (
        <div className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] text-amber-700">
          <ShieldAlert size={12} />
          已载入自定义模式：{mode}
        </div>
      )}

      {error && (
        <div className="inline-flex items-center rounded-full border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs text-rose-700">
          {error}
        </div>
      )}
    </div>
  );
}

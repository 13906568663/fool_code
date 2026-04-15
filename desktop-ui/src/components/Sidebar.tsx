import { useMemo, useState } from "react";
import {
  MessageSquare,
  Plus,
  Search,
  Settings,
  Trash2,
  Sparkles,
  Hash,
  Puzzle,
} from "lucide-react";
import type { SessionListItem } from "../types";

interface SidebarProps {
  sessions: SessionListItem[];
  activeId: string;
  collapsed: boolean;
  busy: boolean;
  onNewChat: () => void;
  onSwitch: (id: string) => void;
  onDelete: (id: string) => void;
  onOpenSettings: () => void;
  onOpenSkillStore: () => void;
}

type SessionGroup = { label: string; items: SessionListItem[] };

function formatTime(ts: number): string {
  const date = new Date(ts * 1000);
  if (Number.isNaN(date.getTime())) return "";

  const now = new Date();
  const sameYear = date.getFullYear() === now.getFullYear();
  const sameDay =
    sameYear &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();

  if (sameDay)
    return new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);

  return new Intl.DateTimeFormat("zh-CN", {
    ...(sameYear ? {} : { year: "2-digit" }),
    month: "numeric",
    day: "numeric",
  }).format(date);
}

function groupByRecency(sessions: SessionListItem[]): SessionGroup[] {
  const dayStart = new Date();
  dayStart.setHours(0, 0, 0, 0);
  const today = dayStart.getTime();
  const week = today - 6 * 86400000;

  const buckets = new Map<string, SessionListItem[]>();
  for (const s of sessions) {
    const t = s.created_at * 1000;
    const label = t >= today ? "今天" : t >= week ? "近 7 天" : "更早";
    const arr = buckets.get(label) ?? [];
    arr.push(s);
    buckets.set(label, arr);
  }

  return ["今天", "近 7 天", "更早"]
    .map((l) => ({ label: l, items: buckets.get(l) ?? [] }))
    .filter((g) => g.items.length > 0);
}

export default function Sidebar({
  sessions,
  activeId,
  collapsed,
  busy,
  onNewChat,
  onSwitch,
  onDelete,
  onOpenSettings,
  onOpenSkillStore,
}: SidebarProps) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const kw = query.trim().toLowerCase();
    return kw ? sessions.filter((s) => s.title.toLowerCase().includes(kw)) : sessions;
  }, [query, sessions]);

  const groups = useMemo(() => groupByRecency(filtered), [filtered]);

  return (
    <div
      className={`sidebar-root flex h-full min-h-0 w-[280px] flex-col overflow-hidden rounded-[28px] border border-[#E4E9F1] transition-all duration-200 ${
        collapsed ? "-ml-[292px] pointer-events-none opacity-0" : "opacity-100"
      }`}
    >
      {/* ── Brand header ── */}
      <div className="relative overflow-hidden px-5 pb-4 pt-5">
        <div className="sidebar-header-glow" />

        <div className="relative flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex size-8 items-center justify-center rounded-xl bg-[#4C84FF] shadow-[0_4px_12px_rgba(76,132,255,0.3)]">
              <Sparkles size={14} className="text-white" />
            </div>
            <div>
              <span className="text-[15px] font-bold tracking-tight text-slate-800">
                Fool Code
              </span>
              <p className="text-[10px] leading-none text-slate-400">
                {sessions.length} 个会话
              </p>
            </div>
          </div>

          <button
            onClick={onNewChat}
            disabled={busy}
            className="sidebar-new-btn inline-flex size-8 items-center justify-center rounded-xl text-white transition disabled:cursor-not-allowed disabled:opacity-50"
            title="新对话"
          >
            <Plus size={15} strokeWidth={2.5} />
          </button>
        </div>

        {/* Search */}
        <div className="relative mt-3.5">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索..."
            className="h-8 w-full rounded-xl border border-[#E7ECF3] bg-white/80 pl-8 pr-3 text-[12px] text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-[#C5D5F7] focus:ring-2 focus:ring-[#EEF4FF]"
          />
        </div>
      </div>

      {/* ── Sessions list ── */}
      <div className="sidebar-list min-h-0 flex-1 overflow-y-auto px-2.5 pb-3">
        {groups.length === 0 ? (
          <div className="mx-1 mt-6 rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-center">
            <MessageSquare className="mx-auto size-7 text-slate-300" />
            <p className="mt-2 text-[12px] leading-5 text-slate-400">
              {query.trim() ? "没有匹配的会话" : "开始你的第一轮对话"}
            </p>
          </div>
        ) : (
          groups.map((group) => (
            <section key={group.label} className="mb-4 last:mb-0">
              <div className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400/70">
                {group.label}
              </div>
              <div className="space-y-0.5">
                {group.items.map((session) => {
                  const active = session.id === activeId;
                  return (
                    <div key={session.id} className="group/item relative">
                      <button
                        type="button"
                        onClick={() => !busy && onSwitch(session.id)}
                        disabled={busy}
                        className={`sidebar-session-btn w-full rounded-xl px-2.5 py-2 pr-8 text-left transition-all ${
                          active
                            ? "sidebar-session-active"
                            : "hover:bg-slate-50 disabled:cursor-not-allowed"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <p
                            className={`min-w-0 truncate text-[13px] font-semibold ${
                              active ? "text-[#3767D6]" : "text-slate-700"
                            }`}
                          >
                            {session.title || "新对话"}
                          </p>
                          <span className="flex-shrink-0 text-[10px] tabular-nums text-slate-400">
                            {formatTime(session.created_at)}
                          </span>
                        </div>
                        <div className="mt-0.5 flex items-center gap-1.5">
                          <Hash size={10} className="flex-shrink-0 text-slate-400/50" />
                          <span className="text-[11px] text-slate-400">
                            {session.message_count} 条消息
                          </span>
                        </div>
                      </button>

                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (!busy) onDelete(session.id);
                        }}
                        disabled={busy}
                        className="absolute right-1.5 top-1/2 -translate-y-1/2 inline-flex size-6 items-center justify-center rounded-lg text-slate-400 opacity-0 transition hover:bg-white hover:text-rose-500 hover:shadow-sm group-hover/item:opacity-100 disabled:cursor-not-allowed"
                        title="删除"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  );
                })}
              </div>
            </section>
          ))
        )}
      </div>

      {/* ── Bottom bar ── */}
      <div className="border-t border-[#EEF2F7]/80 px-3 py-2.5">
        <button
          onClick={onOpenSkillStore}
          className="flex h-9 w-full items-center gap-2 rounded-xl px-2.5 text-[12px] font-medium text-slate-500 transition hover:bg-slate-50 hover:text-slate-700"
        >
          <Puzzle size={14} />
          技能仓库
        </button>
        <button
          onClick={onOpenSettings}
          className="flex h-9 w-full items-center gap-2 rounded-xl px-2.5 text-[12px] font-medium text-slate-500 transition hover:bg-slate-50 hover:text-slate-700"
        >
          <Settings size={14} />
          设置
        </button>
      </div>
    </div>
  );
}

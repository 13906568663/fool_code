import { useState, useEffect, useCallback, useRef } from "react";
import {
  X,
  Search,
  RefreshCw,
  Pin,
  PinOff,
  ToggleLeft,
  ToggleRight,
  Trash2,
  ChevronRight,
  ArrowLeft,
  Puzzle,
  Tag,
  Pencil,
  Network,
  Zap,
  Layers,
  GitFork,
  CheckCircle2,
  ShoppingBag,
  Download,
  Star,
  User,
  Loader2,
} from "lucide-react";
import type {
  SkillStoreInfo,
  SkillStoreDetailResponse,
  SkillStoreStatsResponse,
  SkillRelationsResponse,
  MarketSkillInfo,
} from "../types";
import * as api from "../services/api";
import ConfirmDialog from "./ConfirmDialog";

/* ── 分类中文映射 ── */

const CAT_LABELS: Record<string, string> = {
  "dev-tools": "开发工具",
  "data-processing": "数据处理",
  "deployment": "部署",
  "documentation": "文档",
  "testing": "测试",
  "code-quality": "代码质量",
  "ai-ml": "AI / 机器学习",
  "database": "数据库",
  "frontend": "前端",
  "backend": "后端",
  "devops": "运维",
  "security": "安全",
  "e-commerce": "电商",
  "social-media": "社交媒体",
  "marketing": "营销推广",
  "finance": "金融财务",
  "education": "教育",
  "healthcare": "医疗健康",
  "gaming": "游戏",
  "iot": "物联网",
  "blockchain": "区块链",
  "cloud": "云服务",
  "mobile": "移动端",
  "desktop": "桌面端",
  "cli": "命令行",
  "other": "其他",
  "uncategorized": "未分类",
};

function catLabel(raw: string | null | undefined): string {
  if (!raw) return "未分类";
  return CAT_LABELS[raw] ?? raw;
}

/* ------------------------------------------------------------------ */
/*  主页面                                                            */
/* ------------------------------------------------------------------ */

interface SkillStorePageProps {
  open: boolean;
  onClose: () => void;
}

type ViewMode = "list" | "detail" | "graph" | "market";

export default function SkillStorePage({ open, onClose }: SkillStorePageProps) {
  const [skills, setSkills] = useState<SkillStoreInfo[]>([]);
  const [searchResults, setSearchResults] = useState<SkillStoreInfo[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [stats, setStats] = useState<SkillStoreStatsResponse | null>(null);
  const [search, setSearch] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [detail, setDetail] = useState<SkillStoreDetailResponse | null>(null);
  const [scanning, setScanning] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [ingestProgress, setIngestProgress] = useState<{
    current: number; total: number; skill: string; status: string;
  } | null>(null);
  const [ingestResult, setIngestResult] = useState("");
  const [confirmDialog, setConfirmDialog] = useState<{
    title: string; message: string; variant: "danger" | "warning" | "default";
    confirmText: string; action: () => void;
  } | null>(null);
  const searchDebounce = useRef<ReturnType<typeof setTimeout>>();

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [listRes, statsRes] = await Promise.all([
        api.listSkillStoreSkills(filterCategory ? { category: filterCategory } : undefined),
        api.getSkillStoreStats(),
      ]);
      setSkills(listRes.skills);
      setStats(statsRes);
    } catch { /* ignore */ }
    setLoading(false);
  }, [filterCategory]);

  useEffect(() => { if (open) loadData(); }, [open, loadData]);

  const doSemanticSearch = useCallback((q: string) => {
    if (!q.trim()) {
      setSearchResults(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    api.searchSkillStoreSkills(q, 30)
      .then((r) => setSearchResults(r.skills))
      .catch(() => setSearchResults(null))
      .finally(() => setSearching(false));
  }, []);

  const onSearchChange = (v: string) => {
    setSearch(v);
    clearTimeout(searchDebounce.current);
    if (!v.trim()) {
      setSearchResults(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    searchDebounce.current = setTimeout(() => doSemanticSearch(v), 400);
  };

  const displaySkills = searchResults !== null ? searchResults : skills;
  const isSearchMode = searchResults !== null;

  const openDetail = async (id: string) => {
    try { const d = await api.getSkillStoreDetail(id); setDetail(d); setViewMode("detail"); } catch { /* */ }
  };
  const handleToggleEnabled = async (s: SkillStoreInfo) => {
    try { await api.toggleSkillEnabled(s.id, !s.enabled); setSkills((p) => p.map((x) => x.id === s.id ? { ...x, enabled: !x.enabled } : x)); } catch { /* */ }
  };
  const handleTogglePinned = async (s: SkillStoreInfo) => {
    try { await api.toggleSkillPinned(s.id, !s.pinned); setSkills((p) => p.map((x) => x.id === s.id ? { ...x, pinned: !x.pinned } : x)); } catch { /* */ }
  };
  const handleDelete = (id: string) => {
    setConfirmDialog({
      title: "删除技能",
      message: `确认删除技能「${id}」？此操作不可撤销。`,
      variant: "danger",
      confirmText: "删除",
      action: async () => {
        setConfirmDialog(null);
        try { await api.deleteSkillStore(id); setSkills((p) => p.filter((x) => x.id !== id)); if (viewMode === "detail" && detail?.id === id) { setViewMode("list"); setDetail(null); } } catch { /* */ }
      },
    });
  };

  const runIngest = async (mode: "rescan" | "reindex") => {
    const isScan = mode === "rescan";
    if (isScan) setScanning(true); else setReindexing(true);
    setIngestProgress(null);
    setIngestResult("");
    try {
      const fn = isScan ? api.rescanSkillStore : api.reindexSkillStore;
      await fn((evt) => {
        if (evt.type === "progress") {
          setIngestProgress({ current: evt.current, total: evt.total, skill: evt.skill, status: evt.status });
        } else if (evt.type === "done") {
          setIngestResult(evt.summary);
          setIngestProgress(null);
        } else if (evt.type === "error") {
          setIngestResult(`失败: ${evt.message}`);
          setIngestProgress(null);
        }
      });
      loadData();
    } catch (e) {
      setIngestResult(`${isScan ? "扫描" : "重建"}失败: ${e}`);
      setIngestProgress(null);
    }
    if (isScan) setScanning(false); else setReindexing(false);
  };

  const handleRescan = () => runIngest("rescan");
  const handleReindex = () => {
    setConfirmDialog({
      title: "全量重建",
      message: "全量重建会重新处理所有技能的元数据（描述、触发词等），技能较多时耗时较长。确认继续？",
      variant: "warning",
      confirmText: "开始重建",
      action: () => { setConfirmDialog(null); runIngest("reindex"); },
    });
  };

  if (!open) return null;

  const cats = stats?.categories ? Object.keys(stats.categories).sort() : [];

  return (
    <>
      <div className="fixed inset-0 z-[100] bg-black/20" onClick={onClose} />

      <div className="fixed inset-4 z-[101] flex flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl sm:inset-8 lg:inset-y-10 lg:inset-x-16">

        {/* ── 顶栏 ── */}
        <div className="flex h-[52px] shrink-0 items-center justify-between border-b border-gray-200 px-5">
          <div className="flex items-center gap-2.5">
            {(viewMode === "detail" || viewMode === "graph" || viewMode === "market") && (
              <button onClick={() => { setViewMode("list"); setDetail(null); }} className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
                <ArrowLeft size={16} />
              </button>
            )}
            <Puzzle size={17} className="text-blue-600" />
            <h2 className="text-[15px] font-semibold text-gray-800">技能仓库</h2>
            {stats?.total !== undefined && (
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">{stats.total} 个</span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setViewMode(viewMode === "market" ? "list" : "market")}
              title="技能市场"
              className={`rounded-md p-1.5 transition ${viewMode === "market" ? "bg-blue-50 text-blue-600" : "text-gray-400 hover:bg-gray-100 hover:text-gray-600"}`}
            >
              <ShoppingBag size={16} />
            </button>
            <button
              onClick={() => setViewMode(viewMode === "graph" ? "list" : "graph")}
              title="关系图谱"
              className={`rounded-md p-1.5 transition ${viewMode === "graph" ? "bg-blue-50 text-blue-600" : "text-gray-400 hover:bg-gray-100 hover:text-gray-600"}`}
            >
              <Network size={16} />
            </button>
            <button onClick={onClose} className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
              <X size={16} />
            </button>
          </div>
        </div>

        {/* ── 内容区 ── */}
        {viewMode === "list" ? (
          <div className="flex flex-1 overflow-hidden">

            {/* ── 侧栏 ── */}
            <div className="flex w-56 shrink-0 flex-col border-r border-gray-100 bg-gray-50/60">

              <div className="grid grid-cols-2 gap-1.5 p-3">
                <StatBox icon={<Layers size={13} />} value={stats?.total ?? 0} label="总计" color="blue" />
                <StatBox icon={<Zap size={13} />} value={stats?.has_embeddings ?? 0} label="已索引" color="emerald" />
                <StatBox icon={<Pin size={13} />} value={stats?.pinned ?? 0} label="置顶" color="amber" />
                <StatBox icon={<GitFork size={13} />} value={stats?.edge_count ?? 0} label="关系" color="violet" />
              </div>

              <div className="flex-1 overflow-y-auto px-3 pb-2">
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-gray-400">分类</p>
                <CatBtn active={!filterCategory} onClick={() => setFilterCategory("")} label="全部" count={stats?.total ?? 0} />
                {cats.map((c) => (
                  <CatBtn key={c} active={filterCategory === c} onClick={() => setFilterCategory(filterCategory === c ? "" : c)} label={catLabel(c)} count={stats?.categories?.[c] ?? 0} />
                ))}
              </div>

              <div className="space-y-1.5 border-t border-gray-100 p-3">
                {ingestProgress && (
                  <div className="mb-1">
                    <div className="mb-1 flex items-center justify-between text-[10px] text-gray-500">
                      <span className="truncate max-w-[120px]" title={ingestProgress.skill}>{ingestProgress.skill}</span>
                      <span>{ingestProgress.current}/{ingestProgress.total}</span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-200">
                      <div
                        className="h-full rounded-full bg-blue-500 transition-all duration-300"
                        style={{ width: `${ingestProgress.total > 0 ? (ingestProgress.current / ingestProgress.total) * 100 : 0}%` }}
                      />
                    </div>
                    <p className="mt-0.5 truncate text-[10px] text-gray-400">{ingestProgress.status}</p>
                  </div>
                )}
                <button onClick={handleRescan} disabled={scanning || reindexing} className="flex w-full items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-[7px] text-[12px] font-medium text-white transition hover:bg-blue-700 disabled:opacity-50">
                  <RefreshCw size={13} className={scanning ? "animate-spin" : ""} />
                  {scanning ? "扫描中…" : "扫描新增"}
                </button>
                <button onClick={handleReindex} disabled={scanning || reindexing} className="flex w-full items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-[7px] text-[12px] font-medium text-gray-600 transition hover:bg-gray-50 disabled:opacity-50">
                  <RefreshCw size={13} className={reindexing ? "animate-spin" : ""} />
                  {reindexing ? "重建中…" : "全量重建"}
                </button>
                {ingestResult && <p className="text-[11px] text-emerald-600">{ingestResult}</p>}
              </div>
            </div>

            {/* ── 列表 ── */}
            <div className="flex flex-1 flex-col overflow-hidden">

              <div className="border-b border-gray-100 px-4 py-2.5">
                <div className="relative">
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-300" />
                  <input value={search} onChange={(e) => onSearchChange(e.target.value)} placeholder="语义搜索技能…输入自然语言描述即可" className="w-full rounded-lg border border-gray-200 bg-white py-[7px] pl-9 pr-3 text-[13px] outline-none placeholder:text-gray-300 focus:border-blue-300 focus:ring-2 focus:ring-blue-100" />
                </div>
              </div>

              <div className="flex-1 overflow-y-auto px-4 py-3">
                {isSearchMode && (
                  <div className="mb-2 flex items-center gap-2 text-[11px] text-gray-400">
                    <Search size={11} />
                    <span>语义搜索「{search}」{searching ? " — 检索中…" : ` — 找到 ${displaySkills.length} 个结果`}</span>
                  </div>
                )}
                {loading || (searching && !searchResults) ? (
                  <p className="py-16 text-center text-[13px] text-gray-400">{searching ? "语义检索中…" : "加载中…"}</p>
                ) : displaySkills.length === 0 ? (
                  <div className="flex flex-col items-center py-20 text-gray-400">
                    <Puzzle size={36} strokeWidth={1.2} className="mb-3 text-gray-200" />
                    <p className="text-[13px]">{isSearchMode ? "未找到匹配的技能" : "暂无技能"}</p>
                    <p className="mt-1 text-[11px]">{isSearchMode ? "试试其他搜索词" : "将 SKILL.md 放到 ~/.fool-code/skills/ 目录后重新扫描"}</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {displaySkills.map((sk) => (
                      <SkillCard key={sk.id} skill={sk} isSearchMode={isSearchMode} onOpen={() => openDetail(sk.id)} onToggleEnabled={() => handleToggleEnabled(sk)} onTogglePinned={() => handleTogglePinned(sk)} onDelete={() => handleDelete(sk.id)} />
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : viewMode === "detail" ? (
          detail && <SkillDetailView detail={detail} onDelete={() => handleDelete(detail.id)} onUpdated={() => { openDetail(detail.id); loadData(); }} />
        ) : viewMode === "graph" ? (
          <RelationsGraph />
        ) : viewMode === "market" ? (
          <MarketView />
        ) : null}
      </div>

      <ConfirmDialog
        open={!!confirmDialog}
        title={confirmDialog?.title ?? ""}
        message={confirmDialog?.message ?? ""}
        variant={confirmDialog?.variant ?? "default"}
        confirmText={confirmDialog?.confirmText ?? "确定"}
        onConfirm={() => confirmDialog?.action()}
        onCancel={() => setConfirmDialog(null)}
      />
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  小组件                                                            */
/* ------------------------------------------------------------------ */

function StatBox({ icon, value, label, color }: { icon: React.ReactNode; value: number; label: string; color: string }) {
  const ring: Record<string, string> = { blue: "bg-blue-50 text-blue-600", emerald: "bg-emerald-50 text-emerald-600", amber: "bg-amber-50 text-amber-600", violet: "bg-violet-50 text-violet-600" };
  return (
    <div className="flex items-center gap-2 rounded-lg bg-white p-2 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <span className={`flex h-7 w-7 items-center justify-center rounded-md ${ring[color]}`}>{icon}</span>
      <div className="min-w-0">
        <p className="text-[15px] font-bold leading-none text-gray-800">{value}</p>
        <p className="text-[10px] text-gray-400">{label}</p>
      </div>
    </div>
  );
}

function CatBtn({ active, onClick, label, count }: { active: boolean; onClick: () => void; label: string; count: number }) {
  return (
    <button onClick={onClick} className={`mb-0.5 flex w-full items-center justify-between rounded-md px-2.5 py-[5px] text-[12px] transition ${active ? "bg-blue-50 font-medium text-blue-700" : "text-gray-600 hover:bg-gray-100"}`}>
      <span className="truncate">{label}</span>
      <span className={`text-[11px] ${active ? "text-blue-400" : "text-gray-300"}`}>{count}</span>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  技能卡片                                                          */
/* ------------------------------------------------------------------ */

function SkillCard({ skill, isSearchMode, onOpen, onToggleEnabled, onTogglePinned, onDelete }: {
  skill: SkillStoreInfo; isSearchMode?: boolean; onOpen: () => void; onToggleEnabled: () => void; onTogglePinned: () => void; onDelete: () => void;
}) {
  const triggers = Array.isArray(skill.trigger_terms) ? skill.trigger_terms : [];
  const score = (skill as any).relevance_score as number | undefined;
  return (
    <div className={`group flex items-start gap-3 rounded-xl border px-4 py-3 transition ${skill.enabled ? "border-gray-200 bg-white hover:border-gray-300 hover:shadow-sm" : "border-gray-100 bg-gray-50/60 opacity-55"}`}>
      <div className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${skill.pinned ? "bg-amber-50 text-amber-500" : "bg-blue-50 text-blue-500"}`}>
        {skill.pinned ? <Pin size={16} /> : <Puzzle size={16} />}
      </div>

      <div className="min-w-0 flex-1 cursor-pointer" onClick={onOpen}>
        <div className="flex items-center gap-1.5">
          <h3 className="truncate text-[13px] font-semibold text-gray-800">{skill.display_name}</h3>
          {skill.has_embeddings && <CheckCircle2 size={12} className="shrink-0 text-emerald-400" />}
          {isSearchMode && score !== undefined && (
            <span className="shrink-0 rounded bg-emerald-50 px-1.5 py-px text-[10px] font-medium text-emerald-600">
              {(score * 100).toFixed(0)}%
            </span>
          )}
        </div>
        <p className="mt-0.5 text-[11px] text-gray-400">{skill.id}</p>
        <p className="mt-1 line-clamp-2 text-[12px] leading-[1.5] text-gray-500">{skill.description}</p>

        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {skill.category && (
            <span className="rounded-full bg-blue-50 px-2 py-px text-[10px] font-medium text-blue-600">{catLabel(skill.category)}</span>
          )}
          {triggers.slice(0, 4).map((t) => (
            <span key={t} className="inline-flex items-center gap-0.5 rounded bg-gray-100 px-1.5 py-px text-[10px] text-gray-500">
              <Tag size={8} className="opacity-40" />{t}
            </span>
          ))}
          {triggers.length > 4 && <span className="text-[10px] text-gray-300">+{triggers.length - 4}</span>}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
        <IconBtn title={skill.pinned ? "取消置顶" : "置顶"} onClick={(e) => { e.stopPropagation(); onTogglePinned(); }}>
          {skill.pinned ? <PinOff size={13} /> : <Pin size={13} />}
        </IconBtn>
        <IconBtn title={skill.enabled ? "禁用" : "启用"} onClick={(e) => { e.stopPropagation(); onToggleEnabled(); }}>
          {skill.enabled ? <ToggleRight size={13} className="text-emerald-500" /> : <ToggleLeft size={13} />}
        </IconBtn>
        <IconBtn title="删除" onClick={(e) => { e.stopPropagation(); onDelete(); }} danger>
          <Trash2 size={13} />
        </IconBtn>
        <IconBtn title="查看详情" onClick={onOpen}>
          <ChevronRight size={13} />
        </IconBtn>
      </div>
    </div>
  );
}

function IconBtn({ children, onClick, title, danger }: { children: React.ReactNode; onClick: (e: React.MouseEvent) => void; title: string; danger?: boolean }) {
  return (
    <button onClick={onClick} title={title} className={`rounded-md p-1.5 text-gray-400 transition ${danger ? "hover:bg-red-50 hover:text-red-500" : "hover:bg-gray-100 hover:text-gray-600"}`}>
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  详情视图                                                          */
/* ------------------------------------------------------------------ */

function SkillDetailView({ detail, onDelete, onUpdated }: { detail: SkillStoreDetailResponse; onDelete: () => void; onUpdated: () => void }) {
  const [editing, setEditing] = useState(false);
  const triggers = Array.isArray(detail.trigger_terms) ? detail.trigger_terms : [];

  return (
    <div className="flex flex-1 overflow-hidden">
      <div className="w-72 shrink-0 overflow-y-auto border-r border-gray-100 bg-gray-50/40 p-5">
        <div className="flex items-start justify-between">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold text-gray-800">{detail.display_name}</h2>
            <p className="mt-0.5 text-[11px] text-gray-400">{detail.id}</p>
          </div>
          <button onClick={() => setEditing(true)} title="编辑" className="shrink-0 rounded-md p-1 text-gray-400 hover:bg-blue-50 hover:text-blue-600">
            <Pencil size={14} />
          </button>
        </div>

        <div className="mt-4 space-y-4">
          <Field label="描述">
            <p className="text-[12px] leading-relaxed text-gray-600">{detail.description}</p>
          </Field>

          {detail.category && (
            <Field label="分类">
              <span className="inline-block rounded-full bg-blue-50 px-2.5 py-0.5 text-[11px] font-medium text-blue-600">{catLabel(detail.category)}</span>
            </Field>
          )}

          {triggers.length > 0 && (
            <Field label="触发词">
              <div className="flex flex-wrap gap-1">
                {triggers.map((t) => <span key={t} className="rounded bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600">{t}</span>)}
              </div>
            </Field>
          )}

          {detail.entities.length > 0 && (
            <Field label="关联实体">
              <div className="space-y-1">
                {detail.entities.map((e) => (
                  <div key={e.id} className="flex items-center gap-1.5 text-[11px] text-gray-600">
                    <span className="rounded bg-violet-50 px-1.5 py-px text-[10px] font-medium text-violet-600">{e.entity_type}</span>{e.name}
                  </div>
                ))}
              </div>
            </Field>
          )}

          {detail.edges.length > 0 && (
            <Field label="关联技能">
              <div className="space-y-1">
                {detail.edges.map((e, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-[11px] text-gray-600">
                    <span className="rounded bg-blue-50 px-1.5 py-px text-[10px] font-medium text-blue-600">{edgeLabel(e.edge_type)}</span>
                    {e.source_id === detail.id ? e.target_id : e.source_id}
                  </div>
                ))}
              </div>
            </Field>
          )}

          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <Badge color={detail.enabled ? "emerald" : "red"}>{detail.enabled ? "已启用" : "已禁用"}</Badge>
            {detail.pinned && <Badge color="amber">已置顶</Badge>}
            {detail.has_embeddings && <Badge color="blue">已索引</Badge>}
          </div>
          <p className="text-[10px] text-gray-300">更新于 {new Date(detail.updated_at * 1000).toLocaleString("zh-CN")}</p>

          <button onClick={onDelete} className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-red-200 px-3 py-[7px] text-[12px] font-medium text-red-500 transition hover:bg-red-50">
            <Trash2 size={13} /> 删除此技能
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        <p className="mb-3 text-[12px] font-semibold text-gray-500">技能内容（SKILL.md）</p>
        <pre className="whitespace-pre-wrap rounded-xl border border-gray-100 bg-gray-50/60 p-4 text-[12px] leading-relaxed text-gray-700">
          {detail.body_content || "（无内容）"}
        </pre>
      </div>

      {editing && <EditSkillModal skill={detail} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); onUpdated(); }} />}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-gray-400">{label}</p>{children}</div>;
}

function Badge({ color, children }: { color: string; children: React.ReactNode }) {
  const cls: Record<string, string> = {
    emerald: "bg-emerald-50 text-emerald-600", red: "bg-red-50 text-red-500",
    amber: "bg-amber-50 text-amber-600", blue: "bg-blue-50 text-blue-600",
  };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-medium ${cls[color] ?? "bg-gray-100 text-gray-500"}`}>{children}</span>;
}

/* ── 关系类型中文 ── */

const EDGE_LABELS: Record<string, string> = {
  prerequisite: "前置依赖",
  complementary: "互补配合",
  alternative: "可替代",
  composes_with: "上下游",
  shared_domain: "同领域",
};

function edgeLabel(raw: string): string {
  return EDGE_LABELS[raw] ?? raw;
}

/* ------------------------------------------------------------------ */
/*  关系图谱                                                          */
/* ------------------------------------------------------------------ */

const EDGE_COLORS: Record<string, string> = {
  prerequisite: "#ef4444",
  complementary: "#3b82f6",
  alternative: "#f59e0b",
  composes_with: "#10b981",
  shared_domain: "#8b5cf6",
};

interface GNode { id: string; name: string; category: string | null; x: number; y: number; vx: number; vy: number }

function RelationsGraph() {
  const svgRef = useRef<SVGSVGElement>(null);
  const [data, setData] = useState<SkillRelationsResponse | null>(null);
  const [nodes, setNodes] = useState<GNode[]>([]);
  const [loading, setLoading] = useState(true);
  const animRef = useRef(0);
  const dragging = useRef<string | null>(null);

  useEffect(() => {
    api.getSkillRelations().then((d) => {
      setData(d);
      const w = 800, h = 600;
      setNodes(d.nodes.map((n, i) => ({
        ...n,
        x: w / 2 + Math.cos((i / d.nodes.length) * Math.PI * 2) * w * 0.35,
        y: h / 2 + Math.sin((i / d.nodes.length) * Math.PI * 2) * h * 0.35,
        vx: 0, vy: 0,
      })));
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!data || !nodes.length) return;
    let frame = 0;
    const tick = () => {
      if (frame++ >= 200) return;
      setNodes((prev) => {
        const nx = prev.map((n) => ({ ...n }));
        const w = 800, h = 600;
        for (let i = 0; i < nx.length; i++) for (let j = i + 1; j < nx.length; j++) {
          const dx = nx[j].x - nx[i].x, dy = nx[j].y - nx[i].y;
          const d = Math.sqrt(dx * dx + dy * dy) || 1;
          const f = 8000 / (d * d);
          nx[i].vx -= (dx / d) * f; nx[i].vy -= (dy / d) * f;
          nx[j].vx += (dx / d) * f; nx[j].vy += (dy / d) * f;
        }
        const idxM = new Map(nx.map((n, i) => [n.id, i]));
        for (const e of data.edges) {
          const si = idxM.get(e.source_id), ti = idxM.get(e.target_id);
          if (si === undefined || ti === undefined) continue;
          const dx = nx[ti].x - nx[si].x, dy = nx[ti].y - nx[si].y;
          const d = Math.sqrt(dx * dx + dy * dy) || 1;
          const a = (d - 150) * 0.005;
          nx[si].vx += (dx / d) * a; nx[si].vy += (dy / d) * a;
          nx[ti].vx -= (dx / d) * a; nx[ti].vy -= (dy / d) * a;
        }
        for (const n of nx) { n.vx += (w / 2 - n.x) * 0.001; n.vy += (h / 2 - n.y) * 0.001; }
        for (const n of nx) {
          if (dragging.current === n.id) continue;
          n.vx *= 0.7; n.vy *= 0.7; n.x += n.vx; n.y += n.vy;
          n.x = Math.max(40, Math.min(w - 40, n.x)); n.y = Math.max(40, Math.min(h - 40, n.y));
        }
        return nx;
      });
      animRef.current = requestAnimationFrame(tick);
    };
    animRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animRef.current);
  }, [data, nodes.length]);

  const onDown = (id: string) => { dragging.current = id; };
  const onMove = (e: React.MouseEvent) => {
    if (!dragging.current || !svgRef.current) return;
    const r = svgRef.current.getBoundingClientRect();
    setNodes((p) => p.map((n) => n.id === dragging.current ? { ...n, x: e.clientX - r.left, y: e.clientY - r.top, vx: 0, vy: 0 } : n));
  };
  const onUp = () => { dragging.current = null; };

  if (loading) return <p className="flex flex-1 items-center justify-center text-[13px] text-gray-400">加载关系图…</p>;
  if (!data || !data.nodes.length) return (
    <div className="flex flex-1 flex-col items-center justify-center text-gray-400">
      <Network size={36} strokeWidth={1.2} className="mb-3 text-gray-200" />
      <p className="text-[13px]">暂无关系数据</p>
      <p className="mt-1 text-[11px]">导入技能后，系统会自动发现技能间的关系</p>
    </div>
  );

  const idxM = new Map(nodes.map((n, i) => [n.id, i]));
  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center gap-5 border-b border-gray-100 px-5 py-2.5 text-[11px] text-gray-500">
        <span className="font-medium text-gray-600">图例</span>
        {Object.entries(EDGE_COLORS).map(([t, c]) => (
          <span key={t} className="flex items-center gap-1">
            <span className="inline-block h-[3px] w-4 rounded-full" style={{ backgroundColor: c }} />{edgeLabel(t)}
          </span>
        ))}
      </div>
      <div className="flex-1 overflow-auto p-4">
        <svg ref={svgRef} viewBox="0 0 800 600" className="mx-auto h-full w-full max-w-[900px] rounded-xl border border-gray-100 bg-gray-50/30" onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}>
          <defs>
            {Object.entries(EDGE_COLORS).map(([t, c]) => (
              <marker key={t} id={`arr-${t}`} viewBox="0 0 10 6" refX="10" refY="3" markerWidth="8" markerHeight="6" orient="auto"><path d="M0,0 L10,3 L0,6 Z" fill={c} /></marker>
            ))}
          </defs>
          {data.edges.map((e, i) => {
            const si = idxM.get(e.source_id), ti = idxM.get(e.target_id);
            if (si === undefined || ti === undefined) return null;
            const s = nodes[si], t = nodes[ti]; if (!s || !t) return null;
            return <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke={EDGE_COLORS[e.edge_type] || "#94a3b8"} strokeWidth={1.5} strokeOpacity={0.45} markerEnd={`url(#arr-${e.edge_type})`} />;
          })}
          {nodes.map((n) => (
            <g key={n.id} transform={`translate(${n.x},${n.y})`} onMouseDown={() => onDown(n.id)} className="cursor-grab active:cursor-grabbing">
              <circle r={22} fill="white" stroke="#6366f1" strokeWidth={1.5} />
              <text y={0} textAnchor="middle" dominantBaseline="central" className="pointer-events-none select-none text-[9px] font-medium" fill="#334155">
                {n.name.length > 8 ? n.name.slice(0, 8) + "…" : n.name}
              </text>
              {n.category && <text y={30} textAnchor="middle" className="pointer-events-none select-none text-[7px]" fill="#94a3b8">{catLabel(n.category)}</text>}
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  技能市场                                                          */
/* ------------------------------------------------------------------ */

function MarketView() {
  const [query, setQuery] = useState("");
  const [skills, setSkills] = useState<MarketSkillInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [installing, setInstalling] = useState<string | null>(null);
  const [installMsg, setInstallMsg] = useState<{ slug: string; ok: boolean; text: string } | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    setLoading(true);
    api.getPopularSkills(30)
      .then((r) => setSkills(r.skills))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const doSearch = useCallback((q: string) => {
    if (!q.trim()) {
      setLoading(true);
      api.getPopularSkills(30)
        .then((r) => { setSkills(r.skills); setSearched(false); })
        .catch(() => {})
        .finally(() => setLoading(false));
      return;
    }
    setLoading(true);
    setSearched(true);
    api.searchSkillMarket(q, 30)
      .then((r) => setSkills(r.skills))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const onQueryChange = (v: string) => {
    setQuery(v);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(v), 400);
  };

  const handleInstall = async (slug: string) => {
    setInstalling(slug);
    setInstallMsg(null);
    try {
      const r = await api.installSkillFromMarket(slug);
      setInstallMsg({ slug, ok: true, text: r.message || "下载成功，请点击左侧「扫描新增」将其入库" });
    } catch (e) {
      setInstallMsg({ slug, ok: false, text: `下载失败: ${e}` });
    }
    setInstalling(null);
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="border-b border-gray-100 px-5 py-3">
        <div className="relative mx-auto max-w-xl">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-300" />
          <input
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="搜索在线技能…"
            className="w-full rounded-lg border border-gray-200 bg-white py-[8px] pl-9 pr-3 text-[13px] outline-none placeholder:text-gray-300 focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <p className="mx-auto mt-2 max-w-xl text-[11px] text-gray-400">
          {searched ? `搜索「${query}」的结果` : "热门技能"}
          {!loading && ` · 共 ${skills.length} 个`}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 size={20} className="animate-spin text-blue-400" />
            <span className="ml-2 text-[13px] text-gray-400">加载中…</span>
          </div>
        ) : skills.length === 0 ? (
          <div className="flex flex-col items-center py-20 text-gray-400">
            <ShoppingBag size={36} strokeWidth={1.2} className="mb-3 text-gray-200" />
            <p className="text-[13px]">{searched ? "未找到匹配的技能" : "暂无热门技能"}</p>
            <p className="mt-1 text-[11px]">尝试不同的搜索关键词</p>
          </div>
        ) : (
          <div className="mx-auto grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {skills.map((sk) => (
              <MarketSkillCard
                key={sk.slug}
                skill={sk}
                installing={installing === sk.slug}
                installMsg={installMsg?.slug === sk.slug ? installMsg : null}
                onInstall={() => handleInstall(sk.slug)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MarketSkillCard({ skill, installing, installMsg, onInstall }: {
  skill: MarketSkillInfo;
  installing: boolean;
  installMsg: { ok: boolean; text: string } | null;
  onInstall: () => void;
}) {
  return (
    <div className="flex flex-col rounded-xl border border-gray-200 bg-white p-4 transition hover:border-gray-300 hover:shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[13px] font-semibold text-gray-800">{skill.name}</h3>
          {skill.author && (
            <p className="mt-0.5 flex items-center gap-1 text-[11px] text-gray-400">
              <User size={10} className="shrink-0" />{skill.author}
            </p>
          )}
        </div>
        {skill.staff_pick && (
          <span className="shrink-0 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-600">
            <Star size={9} className="mr-0.5 inline -translate-y-px" />精选
          </span>
        )}
      </div>

      <p className="mt-2 line-clamp-3 flex-1 text-[12px] leading-relaxed text-gray-500">
        {skill.description || "暂无描述"}
      </p>

      <div className="mt-3 flex items-center justify-between">
        <div className="flex items-center gap-3 text-[11px] text-gray-400">
          {skill.downloads > 0 && (
            <span className="flex items-center gap-0.5">
              <Download size={10} />{skill.downloads.toLocaleString()}
            </span>
          )}
          {skill.stars > 0 && (
            <span className="flex items-center gap-0.5">
              <Star size={10} />{skill.stars.toLocaleString()}
            </span>
          )}
          {skill.version && <span>v{skill.version}</span>}
        </div>

        <button
          onClick={onInstall}
          disabled={installing}
          className="flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-[5px] text-[11px] font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
        >
          {installing ? (
            <><Loader2 size={11} className="animate-spin" />下载中…</>
          ) : (
            <><Download size={11} />下载</>
          )}
        </button>
      </div>

      {installMsg && (
        <p className={`mt-2 text-[11px] ${installMsg.ok ? "text-emerald-600" : "text-red-500"}`}>
          {installMsg.text}
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  编辑弹窗                                                          */
/* ------------------------------------------------------------------ */

const CATEGORIES: { value: string; label: string }[] = Object.entries(CAT_LABELS)
  .filter(([v]) => v !== "uncategorized")
  .map(([value, label]) => ({ value, label }));

function EditSkillModal({ skill, onClose, onSaved }: { skill: SkillStoreDetailResponse; onClose: () => void; onSaved: () => void }) {
  const triggers = Array.isArray(skill.trigger_terms) ? skill.trigger_terms : [];
  const [displayName, setDisplayName] = useState(skill.display_name);
  const [description, setDescription] = useState(skill.description);
  const [category, setCategory] = useState(skill.category || "other");
  const [customCat, setCustomCat] = useState(() => {
    const existing = CATEGORIES.find((c) => c.value === (skill.category || "other"));
    return existing ? "" : (skill.category || "");
  });
  const [useCustom, setUseCustom] = useState(() => !CATEGORIES.find((c) => c.value === (skill.category || "other")));
  const [triggerText, setTriggerText] = useState(triggers.join(", "));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const effectiveCategory = useCustom ? customCat.trim().toLowerCase().replace(/\s+/g, "-") : category;

  const save = async () => {
    setSaving(true); setError("");
    try {
      await api.updateSkill(skill.id, { display_name: displayName, description, category: effectiveCategory || "other", trigger_terms: triggerText.split(/[,，]+/).map((t) => t.trim()).filter(Boolean) });
      onSaved();
    } catch (e) { setError(`保存失败: ${e}`); }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="text-[14px] font-semibold text-gray-800">编辑技能 · {skill.id}</h3>
          <button onClick={onClose} className="rounded-md p-1 text-gray-400 hover:bg-gray-100"><X size={16} /></button>
        </div>

        <div className="mt-4 space-y-3">
          <InputField label="显示名称" value={displayName} onChange={setDisplayName} />
          <div>
            <p className="mb-1 text-[11px] font-medium text-gray-500">描述</p>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} className="w-full rounded-lg border border-gray-200 px-3 py-2 text-[13px] outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100" />
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between">
              <p className="text-[11px] font-medium text-gray-500">分类</p>
              <button type="button" onClick={() => setUseCustom(!useCustom)} className="text-[10px] text-blue-500 hover:underline">
                {useCustom ? "选择预设分类" : "自定义分类"}
              </button>
            </div>
            {useCustom ? (
              <input value={customCat} onChange={(e) => setCustomCat(e.target.value)} placeholder="输入自定义分类，如 e-commerce、xiaohongshu" className="w-full rounded-lg border border-gray-200 px-3 py-2 text-[13px] outline-none placeholder:text-gray-300 focus:border-blue-300 focus:ring-2 focus:ring-blue-100" />
            ) : (
              <select value={category} onChange={(e) => setCategory(e.target.value)} className="w-full rounded-lg border border-gray-200 px-3 py-2 text-[13px] outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100">
                {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            )}
          </div>
          <InputField label="触发词（逗号分隔）" value={triggerText} onChange={setTriggerText} placeholder="例如: excel, 表格, 数据" />
          {error && <p className="text-[12px] text-red-500">{error}</p>}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-gray-200 bg-white px-4 py-[7px] text-[13px] text-gray-600 hover:bg-gray-50">取消</button>
          <button onClick={save} disabled={saving} className="rounded-lg bg-blue-600 px-4 py-[7px] text-[13px] font-medium text-white hover:bg-blue-700 disabled:opacity-50">{saving ? "保存中…" : "保存"}</button>
        </div>
      </div>
    </div>
  );
}

function InputField({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div>
      <p className="mb-1 text-[11px] font-medium text-gray-500">{label}</p>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="w-full rounded-lg border border-gray-200 px-3 py-2 text-[13px] outline-none placeholder:text-gray-300 focus:border-blue-300 focus:ring-2 focus:ring-blue-100" />
    </div>
  );
}

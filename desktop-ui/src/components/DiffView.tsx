import { useMemo } from "react";

export interface DiffHunk {
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  lines: string[];
}

interface DiffViewProps {
  hunks: DiffHunk[];
  filePath?: string;
  type?: "create" | "update";
  maxHeight?: string;
}

export default function DiffView({
  hunks,
  filePath,
  type,
  maxHeight = "20rem",
}: DiffViewProps) {
  const { additions, deletions, rows } = useMemo(() => {
    let adds = 0;
    let dels = 0;
    const allRows: {
      kind: "hunk-header" | "add" | "del" | "ctx";
      oldNo?: number;
      newNo?: number;
      text: string;
    }[] = [];

    for (const hunk of hunks) {
      allRows.push({
        kind: "hunk-header",
        text: `@@ -${hunk.oldStart},${hunk.oldLines} +${hunk.newStart},${hunk.newLines} @@`,
      });

      let oldNo = hunk.oldStart;
      let newNo = hunk.newStart;

      for (const raw of hunk.lines) {
        const prefix = raw[0];
        const content = raw.slice(1);

        if (prefix === "-") {
          dels++;
          allRows.push({ kind: "del", oldNo, text: content });
          oldNo++;
        } else if (prefix === "+") {
          adds++;
          allRows.push({ kind: "add", newNo, text: content });
          newNo++;
        } else {
          allRows.push({ kind: "ctx", oldNo, newNo, text: content });
          oldNo++;
          newNo++;
        }
      }
    }

    return { additions: adds, deletions: dels, rows: allRows };
  }, [hunks]);

  if (rows.length === 0) return null;

  const kindStyles: Record<string, string> = {
    "hunk-header":
      "bg-blue-50/60 text-blue-400 select-none text-center italic",
    add: "bg-emerald-50 text-emerald-800",
    del: "bg-red-50 text-red-700 line-through decoration-red-300/60",
    ctx: "text-slate-500",
  };

  const gutterStyles: Record<string, string> = {
    "hunk-header": "bg-blue-50/40",
    add: "bg-emerald-100/50 text-emerald-500",
    del: "bg-red-100/50 text-red-400",
    ctx: "text-slate-300",
  };

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200/80">
      {/* header bar */}
      <div className="flex items-center justify-between bg-slate-50 px-3 py-1.5 text-[11px]">
        <span className="flex items-center gap-2 truncate font-medium text-slate-600">
          {type === "create" ? (
            <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
              NEW
            </span>
          ) : (
            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
              MOD
            </span>
          )}
          {filePath && (
            <span className="truncate font-mono text-slate-500">
              {filePath.replace(/\\/g, "/")}
            </span>
          )}
        </span>
        <span className="flex-shrink-0 font-mono">
          {additions > 0 && (
            <span className="mr-1.5 text-emerald-600">+{additions}</span>
          )}
          {deletions > 0 && (
            <span className="text-red-500">-{deletions}</span>
          )}
        </span>
      </div>

      {/* diff body */}
      <div
        className="overflow-auto font-mono text-[11px] leading-[1.6]"
        style={{ maxHeight }}
      >
        <table className="w-full border-collapse">
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className={kindStyles[row.kind]}>
                {row.kind === "hunk-header" ? (
                  <td
                    colSpan={3}
                    className="px-2 py-0.5 text-[10px]"
                  >
                    {row.text}
                  </td>
                ) : (
                  <>
                    <td
                      className={`w-[1px] whitespace-nowrap border-r border-slate-100 px-1.5 text-right text-[10px] select-none ${gutterStyles[row.kind]}`}
                    >
                      {row.oldNo ?? ""}
                    </td>
                    <td
                      className={`w-[1px] whitespace-nowrap border-r border-slate-100 px-1.5 text-right text-[10px] select-none ${gutterStyles[row.kind]}`}
                    >
                      {row.newNo ?? ""}
                    </td>
                    <td className="whitespace-pre-wrap break-all px-2 py-px">
                      <span className="mr-1 select-none opacity-40">
                        {row.kind === "add"
                          ? "+"
                          : row.kind === "del"
                            ? "-"
                            : " "}
                      </span>
                      {row.text}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

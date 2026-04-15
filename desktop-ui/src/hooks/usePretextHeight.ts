import { useMemo, useRef } from "react";
import { prepare, layout } from "@chenglou/pretext";
import type { DisplayMessage } from "../types";

const FONT = "400 15px system-ui, -apple-system, sans-serif";
const LINE_HEIGHT = 28;
const ASSISTANT_MAX_WIDTH = 820;
const USER_MAX_WIDTH = 500;
const USER_CHROME = 56; // bubble padding (py-3.5*2=28) + wrapper pb-6 (24) + border
const ASSISTANT_CHROME = 32; // less chrome, no bubble border
const TOOL_BLOCK_HEIGHT = 48;
const THINKING_BLOCK_HEIGHT = 44;
const MIN_HEIGHT = 60;

function estimateSingle(content: string, role: "user" | "assistant"): number {
  if (!content) return MIN_HEIGHT;
  const maxWidth = role === "user" ? USER_MAX_WIDTH : ASSISTANT_MAX_WIDTH;
  try {
    const prepared = prepare(content, FONT);
    const { height } = layout(prepared, maxWidth, LINE_HEIGHT);
    const chrome = role === "user" ? USER_CHROME : ASSISTANT_CHROME;
    return Math.max(MIN_HEIGHT, Math.ceil(height + chrome));
  } catch {
    const cpl = Math.floor(maxWidth / 8);
    const lines = Math.ceil(content.length / cpl);
    const chrome = role === "user" ? USER_CHROME : ASSISTANT_CHROME;
    return Math.max(MIN_HEIGHT, lines * LINE_HEIGHT + chrome);
  }
}

export function estimateMessageHeight(msg: DisplayMessage): number {
  let h = estimateSingle(msg.content, msg.role);

  if (msg.role === "assistant") {
    const hasTools = msg.steps.some((s) => s.type === "tool_group");
    if (hasTools) h += TOOL_BLOCK_HEIGHT;
    if (msg.thinking) h += THINKING_BLOCK_HEIGHT;
  }

  return h;
}

/**
 * Maintains a cached map of Pretext-estimated heights per message id,
 * and returns a median-based defaultItemHeight for Virtuoso.
 */
export function usePretextHeights(messages: DisplayMessage[]) {
  const cacheRef = useRef<Map<string, number>>(new Map());

  const { defaultHeight, heightMap } = useMemo(() => {
    const map = cacheRef.current;

    for (const msg of messages) {
      if (!map.has(msg.id) || msg.streaming) {
        map.set(msg.id, estimateMessageHeight(msg));
      }
    }

    // Evict stale entries
    const ids = new Set(messages.map((m) => m.id));
    for (const key of map.keys()) {
      if (!ids.has(key)) map.delete(key);
    }

    if (map.size === 0) return { defaultHeight: 120, heightMap: map };

    const sorted = [...map.values()].sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)];
    return { defaultHeight: median, heightMap: map };
  }, [messages]);

  return { defaultHeight, heightMap };
}

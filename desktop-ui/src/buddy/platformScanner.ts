export interface Platform {
  left: number;
  right: number;
  y: number;
}

const MIN_WIDTH = 60;
const MIN_GAP_Y = 20;

// Selectors that match the actual visual bubble/card elements (not full-width row wrappers)
const BUBBLE_SELECTORS = [
  '[class*="rounded-[26px]"]',   // user message bubble
  '[class*="rounded-2xl"]',       // AI content cards
  '[class*="rounded-xl"]',        // tool blocks
  '[class*="rounded-[20px]"]',   // code block tops/bottoms
  '[class*="rounded-t-[20px]"]', // code block header
].join(", ");

/**
 * Scan for platforms inside the chat container.
 * Uses actual visual bubble/card boundaries, not full-width row containers.
 */
export function scanPlatforms(container: HTMLElement): Platform[] {
  const cRect = container.getBoundingClientRect();
  const raw: Platform[] = [];

  // 1. Floor — always present at the bottom of the container
  raw.push({ left: 0, right: cRect.width, y: cRect.height });

  // 2. Scan inside each Virtuoso message row for the actual visual bubble element
  let items = container.querySelectorAll("[data-item-index]");
  if (items.length === 0) items = container.querySelectorAll("[data-index]");

  for (let i = 0; i < items.length; i++) {
    const item = items[i] as HTMLElement;
    // Find the actual visual card/bubble inside this row
    const bubbles = item.querySelectorAll(BUBBLE_SELECTORS);
    for (let j = 0; j < bubbles.length; j++) {
      const el = bubbles[j] as HTMLElement;
      // Skip tiny elements (inline badges, icons etc.)
      const r = el.getBoundingClientRect();
      if (r.width < MIN_WIDTH || r.height < 20) continue;
      // Skip elements inside buddy overlay
      if (el.closest("[data-buddy-overlay]")) continue;
      addPlatform(raw, cRect, r.left, r.right, r.top);
      // Only use the first sufficiently large bubble per row to avoid
      // scanning all inner rounded elements redundantly
      break;
    }
  }

  // 3. Code blocks and pre elements (may exist inside AI messages)
  const codeBlocks = container.querySelectorAll("pre");
  for (let i = 0; i < codeBlocks.length; i++) {
    const el = codeBlocks[i] as HTMLElement;
    if (el.closest("[data-buddy-overlay]")) continue;
    const r = el.getBoundingClientRect();
    if (r.width < MIN_WIDTH || r.height < 30) continue;
    addPlatform(raw, cRect, r.left, r.right, r.top);
  }

  // 4. Sibling elements below the container (InputArea, PermissionBar)
  const parent = container.parentElement;
  if (parent) {
    for (let i = 0; i < parent.children.length; i++) {
      const sib = parent.children[i] as HTMLElement;
      if (sib === container || sib.hasAttribute("data-buddy-overlay")) continue;
      const r = sib.getBoundingClientRect();
      if (r.width < MIN_WIDTH) continue;
      const relY = r.top - cRect.top;
      if (relY > 0 && relY < cRect.height + 5) {
        raw.push({
          left: Math.max(0, r.left - cRect.left),
          right: Math.min(cRect.width, r.right - cRect.left),
          y: Math.min(relY, cRect.height - 4),
        });
      }
    }
  }

  // Sort by y
  raw.sort((a, b) => a.y - b.y);

  // Merge only platforms that are very close in Y AND horizontally overlapping
  const merged: Platform[] = [];
  for (const p of raw) {
    const last = merged[merged.length - 1];
    if (
      last &&
      Math.abs(last.y - p.y) < MIN_GAP_Y &&
      p.left < last.right &&
      p.right > last.left
    ) {
      last.left = Math.min(last.left, p.left);
      last.right = Math.max(last.right, p.right);
    } else {
      merged.push({ ...p });
    }
  }

  return merged;
}

function addPlatform(
  list: Platform[],
  cRect: DOMRect,
  absLeft: number,
  absRight: number,
  absY: number,
) {
  const relY = absY - cRect.top;
  if (relY < -20 || relY > cRect.height + 10) return;
  const left = Math.max(0, absLeft - cRect.left);
  const right = Math.min(cRect.width, absRight - cRect.left);
  if (right - left < MIN_WIDTH) return;
  list.push({ left, right, y: relY });
}

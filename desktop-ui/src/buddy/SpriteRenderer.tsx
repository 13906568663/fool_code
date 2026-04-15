import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
} from "react";

import idleUrl from "./assets/idle.png";
import walkUrl from "./assets/walk.png";
import sitUrl from "./assets/sit.png";
import climbUrl from "./assets/climb.png";
import sleepUrl from "./assets/sleep.png";
import petUrl from "./assets/pet.png";
import grabUrl from "./assets/grab.png";
import dizzyUrl from "./assets/dizzy.png";
import clamberUrl from "./assets/clamber.png";
export type CatAction = "idle" | "walk" | "sit" | "climb" | "sleep" | "pet" | "grab" | "dizzy" | "clamber";

interface SpriteSource {
  url: string;
  cols: number;
  rows: number;
}

const SOURCES: Record<CatAction, SpriteSource> = {
  idle:  { url: idleUrl,  cols: 1, rows: 1 },
  walk:  { url: walkUrl,  cols: 4, rows: 2 },
  sit:   { url: sitUrl,   cols: 1, rows: 1 },
  climb: { url: climbUrl, cols: 1, rows: 1 },
  sleep: { url: sleepUrl, cols: 1, rows: 1 },
  pet:   { url: petUrl,   cols: 2, rows: 1 },
  grab:  { url: grabUrl,  cols: 3, rows: 2 },
  dizzy:   { url: dizzyUrl,   cols: 2, rows: 2 },
  clamber: { url: clamberUrl, cols: 3, rows: 2 },
};

export const ANIM_SPEEDS: Record<CatAction, number> = {
  idle: 800,
  walk: 180,
  sit: 1200,
  climb: 600,
  sleep: 1500,
  pet: 350,
  grab: 120,
  dizzy: 300,
  clamber: 380,
};

export const FRAME_COUNTS: Record<CatAction, number> = {
  idle: 1,
  walk: 8,
  sit: 1,
  climb: 1,
  sleep: 1,
  pet: 2,
  grab: 6,
  dizzy: 4,
  clamber: 6,
};

const DISPLAY_H = 72;

function isGreen(r: number, g: number, b: number): boolean {
  return g > 180 && r < 120 && b < 120;
}

// ---------------------------------------------------------------------------
// Pre-extract ALL action bitmaps at startup
// ---------------------------------------------------------------------------

type AllBitmaps = Record<CatAction, ImageBitmap[]>;
let _allBitmaps: AllBitmaps | null = null;
let _loadPromise: Promise<AllBitmaps> | null = null;

async function loadAllBitmaps(): Promise<AllBitmaps> {
  if (_allBitmaps) return _allBitmaps;
  if (_loadPromise) return _loadPromise;

  _loadPromise = (async () => {
    const actions = Object.keys(SOURCES) as CatAction[];
    const results = {} as AllBitmaps;

    await Promise.all(
      actions.map(async (action) => {
        const src = SOURCES[action];
        const img = await loadImage(src.url);
        results[action] = await extractBitmaps(img, src);
      }),
    );

    _allBitmaps = results;
    return results;
  })();

  return _loadPromise;
}

async function extractBitmaps(
  img: HTMLImageElement,
  src: SpriteSource,
): Promise<ImageBitmap[]> {
  const sw = img.width;
  const sh = img.height;
  const cellW = Math.floor(sw / src.cols);
  const cellH = Math.floor(sh / src.rows);
  const total = src.cols * src.rows;

  const srcCanvas = document.createElement("canvas");
  srcCanvas.width = sw;
  srcCanvas.height = sh;
  const srcCtx = srcCanvas.getContext("2d")!;
  srcCtx.drawImage(img, 0, 0);
  const fullData = srcCtx.getImageData(0, 0, sw, sh);

  const bitmaps: ImageBitmap[] = [];

  const insetLR = Math.max(2, Math.floor(cellW * 0.02));
  const insetTB = 1;

  for (let f = 0; f < total; f++) {
    const col = f % src.cols;
    const row = Math.floor(f / src.cols);
    const ox = col * cellW;
    const oy = row * cellH;

    const cellCanvas = document.createElement("canvas");
    cellCanvas.width = cellW;
    cellCanvas.height = cellH;
    const cellCtx = cellCanvas.getContext("2d")!;
    const cellData = cellCtx.createImageData(cellW, cellH);

    let minX = cellW, minY = cellH, maxX = 0, maxY = 0;

    for (let y = 0; y < cellH; y++) {
      for (let x = 0; x < cellW; x++) {
        const si = ((oy + y) * sw + (ox + x)) * 4;
        const di = (y * cellW + x) * 4;
        const r = fullData.data[si]!;
        const g = fullData.data[si + 1]!;
        const b = fullData.data[si + 2]!;
        const a = fullData.data[si + 3]!;

        if (isGreen(r, g, b) || x < insetLR || x >= cellW - insetLR || y < insetTB || y >= cellH - insetTB) {
          cellData.data[di + 3] = 0;
        } else {
          cellData.data[di] = r;
          cellData.data[di + 1] = g;
          cellData.data[di + 2] = b;
          cellData.data[di + 3] = a;
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
    }

    const pad = 2;
    minX = Math.max(0, minX - pad);
    minY = Math.max(0, minY - pad);
    maxX = Math.min(cellW - 1, maxX + pad);
    maxY = Math.min(cellH - 1, maxY + pad);

    cellCtx.putImageData(cellData, 0, 0);
    const bmp = await createImageBitmap(
      cellCanvas, minX, minY, maxX - minX + 1, maxY - minY + 1,
    );
    bitmaps.push(bmp);
  }

  return bitmaps;
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = url;
  });
}

// ---------------------------------------------------------------------------
// Imperative handle: parent drives everything from rAF
// ---------------------------------------------------------------------------

export interface SpriteHandle {
  /** Draw the given frame index for the given action. Fully imperative. */
  draw: (action: CatAction, frameIndex: number) => void;
  setFlip: (right: boolean) => void;
  ready: boolean;
}

interface SpriteRendererProps {
  onClick?: () => void;
}

const SpriteRenderer = forwardRef<SpriteHandle, SpriteRendererProps>(
  function SpriteRenderer({ onClick }, ref) {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const bitmapsRef = useRef<AllBitmaps | null>(_allBitmaps);
    const lastKeyRef = useRef("");

    useEffect(() => {
      if (!bitmapsRef.current) {
        loadAllBitmaps().then((b) => {
          bitmapsRef.current = b;
        });
      }
    }, []);

    useImperativeHandle(ref, () => ({
      get ready() {
        return bitmapsRef.current !== null;
      },

      draw(action: CatAction, frameIndex: number) {
        const all = bitmapsRef.current;
        if (!all || !canvasRef.current) return;
        const frames = all[action];
        if (!frames || frames.length === 0) return;

        const idx = frameIndex % frames.length;
        const key = `${action}:${idx}`;
        if (key === lastKeyRef.current) return;
        lastKeyRef.current = key;

        const bmp = frames[idx]!;
        const canvas = canvasRef.current;
        const scale = DISPLAY_H / bmp.height;
        const w = Math.round(bmp.width * scale);
        if (canvas.width !== w) canvas.width = w;
        if (canvas.height !== DISPLAY_H) canvas.height = DISPLAY_H;
        const ctx = canvas.getContext("2d")!;
        ctx.imageSmoothingEnabled = false;
        ctx.clearRect(0, 0, w, DISPLAY_H);
        ctx.drawImage(bmp, 0, 0, w, DISPLAY_H);
      },

      setFlip(right: boolean) {
        if (canvasRef.current) {
          canvasRef.current.style.transform = `scaleX(${right ? 1 : -1})`;
        }
      },
    }), []);

    return (
      <canvas
        ref={canvasRef}
        onClick={onClick}
        style={{
          height: DISPLAY_H,
          imageRendering: "pixelated",
          cursor: onClick ? "pointer" : "default",
          pointerEvents: onClick ? "auto" : "none",
          userSelect: "none",
        }}
      />
    );
  },
);

export default SpriteRenderer;

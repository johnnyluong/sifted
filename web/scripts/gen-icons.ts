import { deflateSync } from "node:zlib";

const OUT = new URL("../public/", import.meta.url);
const PAN: Rgb = [243, 244, 246];
// The maskable safe zone is a circle of radius 0.4; the margin covers antialiasing.
const SAFE_RADIUS = 0.4;
const MARK_REACH = 0.38;
const SEGMENT = /M([\d.]+) ([\d.]+)h([\d.]+)/g;

type Rgb = [number, number, number];
type Stroke = { x1: number; x2: number; y: number; color: Rgb };
type Mark = { cx: number; cy: number; halfWidth: number; strokes: Stroke[] };

function parseMark(svg: string): Mark {
  const [minX = 0, minY = 0, width = 0, height = 0] = match(svg, /viewBox="([^"]+)"/)
    .split(" ")
    .map(Number);
  const classColors = new Map<string, string>();
  for (const [, name = "", color = ""] of svg.matchAll(/\.([\w-]+)\{stroke:(#[0-9a-f]{6})\}/g)) {
    if (!classColors.has(name)) classColors.set(name, color);
  }
  const strokes: Stroke[] = [];
  for (const [, attrs = ""] of svg.matchAll(/<path\b([^>]*)\/>/g)) {
    const attr = (name: string) => attrs.match(new RegExp(`\\b${name}="([^"]*)"`))?.[1];
    const color = attr("stroke") ?? classColors.get(attr("class") ?? "");
    const d = attr("d") ?? "";
    if (!color || d.replace(SEGMENT, "") !== "") {
      throw new Error(`favicon.svg: expected horizontal "Mx yhw" paths with a stroke color, got ${attrs}`);
    }
    for (const [, x, y, w] of d.matchAll(SEGMENT)) {
      strokes.push({ x1: Number(x), x2: Number(x) + Number(w), y: Number(y), color: rgb(color) });
    }
  }
  return {
    cx: minX + width / 2,
    cy: minY + height / 2,
    halfWidth: Number(match(svg, /stroke-width="([\d.]+)"/)) / 2,
    strokes,
  };
}

function match(text: string, pattern: RegExp): string {
  const found = text.match(pattern)?.[1];
  if (found === undefined) throw new Error(`favicon.svg: no match for ${pattern}`);
  return found;
}

function rgb(hex: string): Rgb {
  return [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16)) as Rgb;
}

function reach(mark: Mark): number {
  const ends = mark.strokes.flatMap((s) => [s.x1, s.x2].map((x) => Math.hypot(x - mark.cx, s.y - mark.cy)));
  return Math.max(...ends) + mark.halfWidth;
}

function coverage(px: number, py: number, unit: number, halfWidth: number, s: Stroke): number {
  const dx = px < s.x1 ? s.x1 - px : px > s.x2 ? px - s.x2 : 0;
  const edge = (Math.hypot(dx, py - s.y) - halfWidth) * unit;
  return Math.min(1, Math.max(0, 0.5 - edge));
}

function render(size: number, mark: Mark): Buffer {
  const unit = (size * MARK_REACH) / reach(mark);
  const stride = size * 3 + 1;
  const rows = Buffer.alloc(size * stride);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const px = (x + 0.5 - size / 2) / unit + mark.cx;
      const py = (y + 0.5 - size / 2) / unit + mark.cy;
      let color: Rgb = PAN;
      for (const stroke of mark.strokes) {
        const alpha = coverage(px, py, unit, mark.halfWidth, stroke);
        color = color.map((c, i) => c + ((stroke.color[i] ?? 0) - c) * alpha) as Rgb;
      }
      rows.set(
        color.map((c) => Math.round(c)),
        y * stride + 1 + x * 3,
      );
    }
  }
  assertInsideSafeZone(size, rows);
  return rows;
}

function assertInsideSafeZone(size: number, rows: Buffer): void {
  const stride = size * 3 + 1;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if (Math.hypot(x + 0.5 - size / 2, y + 0.5 - size / 2) <= SAFE_RADIUS * size) continue;
      const at = y * stride + 1 + x * 3;
      if (PAN.some((c, i) => rows[at + i] !== c)) {
        throw new Error(`${size}px icon: pixel (${x}, ${y}) is inked outside the maskable safe circle`);
      }
    }
  }
}

function png(size: number, rows: Buffer): Buffer {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header.set([8, 2, 0, 0, 0], 8);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(rows, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

function chunk(kind: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(kind, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

function crc32(data: Buffer): number {
  let crc = ~0;
  for (const byte of data) {
    crc ^= byte;
    for (let k = 0; k < 8; k++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return ~crc >>> 0;
}

const mark = parseMark(await Bun.file(new URL("favicon.svg", OUT)).text());
for (const [name, size] of [
  ["apple-touch-icon.png", 180],
  ["icon-192.png", 192],
  ["icon-512.png", 512],
] as const) {
  await Bun.write(new URL(name, OUT), png(size, render(size, mark)));
  console.log(`wrote public/${name}`);
}

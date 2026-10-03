import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import { chromium } from "playwright";
import { renderMermaidSVG } from "beautiful-mermaid";

type Args = Record<string, string | boolean>;

function parseArgs(argv: string[]): Args {
  const result: Args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index] || "";
    if (!token.startsWith("--")) {
      continue;
    }
    const key = token.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      result[key] = true;
      continue;
    }
    result[key] = next;
    index += 1;
  }
  return result;
}

function textArg(args: Args, key: string): string {
  const value = args[key];
  return typeof value === "string" ? value.trim() : "";
}

function requireTextArg(args: Args, key: string): string {
  const value = textArg(args, key);
  if (!value) {
    throw new Error(`Missing required --${key}`);
  }
  return value;
}

function inferSvgSize(svg: string): { width: number; height: number } {
  const viewBox = svg.match(/viewBox="[^"]*?\s([0-9.]+)\s([0-9.]+)"/i);
  if (viewBox) {
    return {
      width: Math.max(1, Math.ceil(Number(viewBox[1]) || 0)),
      height: Math.max(1, Math.ceil(Number(viewBox[2]) || 0)),
    };
  }
  const width = svg.match(/\bwidth="([0-9.]+)"/i);
  const height = svg.match(/\bheight="([0-9.]+)"/i);
  return {
    width: Math.max(1, Math.ceil(Number(width?.[1]) || 1280)),
    height: Math.max(1, Math.ceil(Number(height?.[1]) || 760)),
  };
}

function injectTitle(svg: string, title: string): string {
  const cleanTitle = title.trim();
  if (!cleanTitle || /<title\b/i.test(svg)) {
    return svg;
  }
  return svg.replace(/<svg\b([^>]*)>/i, (match) => `${match}<title>${escapeXml(cleanTitle)}</title>`);
}

function escapeXml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function renderPngFromSvg(svg: string, outputPath: string): Promise<{ width: number; height: number; scale: number }> {
  const size = inferSvgSize(svg);
  const scale = Math.min(2.4, Math.max(1, 1120 / size.width));
  const width = Math.ceil(size.width * scale);
  const height = Math.ceil(size.height * scale);
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({
      viewport: { width: Math.max(640, width + 96), height: Math.max(360, height + 96) },
      deviceScaleFactor: 2,
    });
    await page.setContent(
      `<!doctype html><html><head><meta charset="utf-8"><style>
        html,body{margin:0;padding:0;background:#fff;}
        body{display:flex;align-items:center;justify-content:center;min-width:${width + 80}px;min-height:${height + 80}px;}
        #diagram{display:inline-flex;align-items:center;justify-content:center;background:#fff;padding:40px;}
        svg{display:block;width:${width}px!important;height:${height}px!important;max-width:none!important;max-height:none!important;}
      </style></head><body><div id="diagram">${svg}</div></body></html>`,
      { waitUntil: "load" },
    );
    await page.locator("#diagram").screenshot({ path: outputPath, type: "png" });
  } finally {
    await browser.close();
  }
  return { width, height, scale };
}

function stripMermaidComments(source: string): string {
  return source
    .split(/\r?\n/)
    .filter((line) => !line.trim().startsWith("%%"))
    .join("\n")
    .trim();
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const inputFile = requireTextArg(args, "input-file");
  const svgOutput = requireTextArg(args, "svg-output");
  const pngOutput = textArg(args, "png-output");
  const metaOutput = textArg(args, "meta-output");
  const title = textArg(args, "title") || "正文图解";
  const source = stripMermaidComments(await fs.readFile(inputFile, "utf8"));
  if (!source) {
    throw new Error("Mermaid source is empty.");
  }
  const svg = injectTitle(
    renderMermaidSVG(source, {
      bg: "#ffffff",
      fg: "#111827",
      line: "#8fb1ef",
      accent: "#2f68d7",
      muted: "#64748b",
      surface: "#f1f6ff",
      border: "#cbdaf2",
      font: "Arial, sans-serif",
      padding: 42,
      nodeSpacing: 30,
      layerSpacing: 52,
      componentSpacing: 32,
      thoroughness: 5,
    } as any),
    title,
  );
  await fs.mkdir(path.dirname(svgOutput), { recursive: true });
  await fs.writeFile(svgOutput, svg, "utf8");
  const svgSize = inferSvgSize(svg);
  const pngMeta = pngOutput ? await renderPngFromSvg(svg, pngOutput) : null;
  const meta = {
    status: "ok",
    renderer: "beautiful-mermaid",
    renderer_version: "beautiful-mermaid-1.1.3-aimagician-v3",
    title,
    svg_output: svgOutput,
    png_output: pngOutput || "",
    width: pngMeta?.width || svgSize.width,
    height: pngMeta?.height || svgSize.height,
    intrinsic_width: svgSize.width,
    intrinsic_height: svgSize.height,
    png_scale: pngMeta?.scale || 1,
    background: "white",
  };
  if (metaOutput) {
    await fs.mkdir(path.dirname(metaOutput), { recursive: true });
    await fs.writeFile(metaOutput, `${JSON.stringify(meta, null, 2)}\n`, "utf8");
  }
  console.log(JSON.stringify(meta));
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(JSON.stringify({ status: "error", failure_code: "mermaid_render_failed", failure_message: message }));
  process.exit(1);
});

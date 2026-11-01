#!/usr/bin/env node
/**
 * 画布交互基线状态统计（E6）。
 *
 * 唯一事实源是 docs/canvas-roadmap.md §13.8 的 Markdown 表：
 * 本脚本直接解析表格，不维护第二份数据；新增/修改行无需改脚本。
 *
 * 用法：
 *   node scripts/canvas-status.mjs
 *   node scripts/canvas-status.mjs --unfinished
 *   node scripts/canvas-status.mjs --json
 *
 * 退出码：
 *   0 正常；1 表格出现未知状态标记（防止新图标悄悄漏统计）。
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const ROADMAP = join(ROOT, 'docs', 'canvas-roadmap.md');
const SECTION_START = '### 13.8';
const UNFINISHED = new Set(['⬜', '🟧', '🟨']);
const KNOWN_STATUS = new Set(['✅', '🟨', '🟧', '⬜', '⛔']);
const STATUS_LABELS = {
  '✅': '已完成',
  '🟨': '已实现未验收',
  '🟧': '部分实现',
  '⬜': '未实现',
  '⛔': '已裁决不做',
};

/** 提取 13.8 章节正文（到下一个二级标题为止）。 */
function readBaselineSection(markdown) {
  const start = markdown.indexOf(SECTION_START);
  if (start === -1) throw new Error(`未找到章节 ${SECTION_START}`);
  const rest = markdown.slice(start);
  const nextHeading = rest.slice(SECTION_START.length).indexOf('\n### ');
  return nextHeading === -1 ? rest : rest.slice(0, SECTION_START.length + nextHeading);
}

/** 拆 Markdown 表格行；非表格行返回 null。 */
function splitRow(line) {
  const trimmed = line.trim();
  if (!trimmed.startsWith('|')) return null;
  const cells = trimmed.replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
  if (cells.every((cell) => /^:?-{3,}:?$/.test(cell))) return null;
  return cells;
}

/** 解析 13.8 的七列表格（# / 交互项 / Coze / Dify / 实现 / 状态 / 任务）。 */
function parseItems(section) {
  const items = [];
  let layer = { key: '', title: '未分组' };
  for (const line of section.split(/\r?\n/)) {
    const heading = line.match(/^####\s+([A-Z])\.\s*(.+)$/);
    if (heading) {
      layer = { key: heading[1], title: heading[2] };
      continue;
    }
    const cells = splitRow(line);
    if (!cells || cells.length !== 7) continue;
    const [no, item, , , , rawStatus, ref] = cells;
    if (no === '#' || !no) continue;
    const status = [...KNOWN_STATUS].find((icon) => rawStatus.startsWith(icon));
    items.push({
      layer: layer.key,
      layerTitle: layer.title,
      no,
      item,
      status: status || rawStatus,
      ref,
    });
  }
  return items;
}

function countBy(items) {
  const counts = {};
  for (const item of items) counts[item.status] = (counts[item.status] || 0) + 1;
  return counts;
}

function formatCounts(items) {
  const counts = countBy(items);
  return Object.keys(STATUS_LABELS)
    .filter((icon) => counts[icon])
    .map((icon) => `${icon} ${counts[icon]}`)
    .join(' / ');
}

function printText(items) {
  const unfinished = items.filter((item) => UNFINISHED.has(item.status));
  console.log('画布交互基线（docs/canvas-roadmap.md §13.8）');
  console.log(`总计 ${items.length} 项：${formatCounts(items)}`);
  console.log('');

  const layers = [];
  for (const item of items) {
    const current = layers[layers.length - 1];
    if (!current || current.key !== item.layer) {
      layers.push({ key: item.layer, title: item.layerTitle, items: [] });
    }
    layers[layers.length - 1].items.push(item);
  }
  console.log('按层级：');
  for (const layer of layers) {
    console.log(`  ${layer.key}. ${layer.title}（${layer.items.length} 项）：${formatCounts(layer.items)}`);
  }
  console.log('');
  console.log(`未完成（⬜ 未实现 / 🟧 部分实现 / 🟨 已实现未验收）：${unfinished.length} 项`);
  for (const item of unfinished) {
    console.log(`  ${item.status} ${item.no} ${item.item} — ${item.ref}`);
  }
}

const args = new Set(process.argv.slice(2));
const markdown = readFileSync(ROADMAP, 'utf8');
const items = parseItems(readBaselineSection(markdown));

const unknown = items.filter((item) => !KNOWN_STATUS.has(item.status));
if (unknown.length > 0) {
  console.error('13.8 存在未知状态标记，请补充到 canvas-status.mjs 的 KNOWN_STATUS：');
  for (const item of unknown) console.error(`  ${item.no} ${item.item} — ${item.status}`);
  process.exit(1);
}

if (items.length === 0) {
  console.error('13.8 未解析到任何交互项，请检查表格格式。');
  process.exit(1);
}

if (args.has('--json')) {
  console.log(JSON.stringify({ total: items.length, counts: countBy(items), items }, null, 2));
} else if (args.has('--unfinished')) {
  for (const item of items.filter((entry) => UNFINISHED.has(entry.status))) {
    console.log(`${item.status} ${item.no} ${item.item} — ${item.ref}`);
  }
} else {
  printText(items);
}

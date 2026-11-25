// Bundles the twin with its sample data into one HTML file that opens from disk, with no server and
// no network: preview/windfarm-twin-preview.html.
//   node build-preview.mjs
import { build } from 'esbuild';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const result = await build({
  absWorkingDir: here,
  entryPoints: ['preview-main.tsx'],
  bundle: true,
  minify: true,
  format: 'iife',
  target: ['es2022'],
  jsx: 'automatic',
  define: { 'process.env.NODE_ENV': '"production"' },
  outdir: 'out',
  write: false,
  legalComments: 'none',
  logLevel: 'warning',
});
const js = result.outputFiles.find((f) => f.path.endsWith('.js'))?.text ?? '';
const css = result.outputFiles.find((f) => f.path.endsWith('.css'))?.text ?? '';
if (!js || !css) throw new Error('The bundle has no script or no style sheet.');
const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Northwind Ridge Wind Farm: 3D twin, preview on sample data</title>
<style>html,body{margin:0;height:100%;background:#0e161f}${css}</style>
</head>
<body>
<div id="root"></div>
<script>${js.replace(/<\/script/g, '<\\/script')}</script>
</body>
</html>
`;
await mkdir(path.join(here, 'preview'), { recursive: true });
await writeFile(path.join(here, 'preview', 'windfarm-twin-preview.html'), html);
console.log(`wrote preview/windfarm-twin-preview.html (${Math.round(html.length / 1024)} KB)`);

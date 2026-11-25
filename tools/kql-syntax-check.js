// Syntax-check the KQL scripts offline with the Kusto language service.
//   npm install --no-save @kusto/language-service-next
//   node tools/kql-syntax-check.js fabric/kql/*.kql
// The "policy mirroring" commands in 03-onelake-availability.kql are skipped: they follow the
// syntax in the Fabric documentation, which this client-side parser does not know.
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const base = path.join(path.dirname(require.resolve('@kusto/language-service-next/package.json')), '/');
global.window = global; global.document = undefined; global.navigator = { userAgent: 'node' };
for (const f of ['bridge.min.js', 'Kusto.Language.Bridge.min.js']) {
  vm.runInThisContext(fs.readFileSync(base + f, 'utf8'), { filename: f });
}
const KustoCode = Kusto.Language.KustoCode;
function diags(text) {
  const code = KustoCode.Parse(text);
  const list = code.GetDiagnostics();
  const out = [];
  for (let i = 0; i < list.Count; i++) {
    const d = list.getItem ? list.getItem(i) : list.Items[i];
    const line = text.slice(0, d.Start).split('\n').length;
    out.push(`  line ${line}: [${d.Severity}] ${d.Message} near "${text.slice(d.Start, d.Start + Math.max(d.Length, 1)).slice(0, 40)}"`);
  }
  return out;
}
let failures = 0;
for (const file of process.argv.slice(2)) {
  const text = fs.readFileSync(file, 'utf8');
  // blocks are separated by empty lines, as in the query editor
  const blocks = text.split(/\n\s*\n/).map(b => b.trim()).filter(b => b && !b.split('\n').every(l => l.startsWith('//')));
  console.log(`${file}: ${blocks.length} block(s)`);
  for (const block of blocks) {
    const first = block.split('\n').find(l => !l.startsWith('//')) || '';
    let units = [block];
    if (first.startsWith('.execute database script')) {
      // check each command of the script on its own
      const body = block.slice(block.indexOf('<|') + 2);
      units = []; let cur = [];
      for (const l of body.split('\n')) {
        if (l.startsWith('//')) continue;
        if (l.startsWith('.') && cur.length) { units.push(cur.join('\n')); cur = []; }
        if (l.trim()) cur.push(l);
      }
      if (cur.length) units.push(cur.join('\n'));
    }
    for (const u of units) {
      if (/policy mirroring/.test(u)) continue;
      const d = diags(u);
      if (d.length) { failures++; console.log(` PROBLEM in: ${u.split('\n').find(l => !l.startsWith('//')).slice(0, 90)}`); d.forEach(x => console.log(x)); }
    }
    console.log(`  ok-checked ${units.length} unit(s) starting "${first.slice(0, 60)}"`);
  }
}
console.log(failures ? `${failures} unit(s) with diagnostics` : 'no syntax diagnostics');

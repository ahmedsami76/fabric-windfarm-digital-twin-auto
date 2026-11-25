// Check the KQL scripts against the tables of the database, offline: unknown columns and
// tables, wrong argument types, wrong argument counts. The syntax check next to this file
// (kql-syntax-check.js) only reads the grammar; this one also knows what the tables hold.
//   npm install --no-save @kusto/language-service-next
//   node tools/kql-semantic-check.js fabric/kql/*.kql
// What it does: it reads every ".create-merge table" command of the given files for the
// columns, checks the body of every stored function as a query, and then checks every query
// block, with the stored functions it calls placed in front of it as "let" statements.
// What it cannot tell: whether a query returns the rows you expect. That needs the database.
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const base = path.join(path.dirname(require.resolve('@kusto/language-service-next/package.json')), '/');
global.window = global; global.document = undefined; global.navigator = { userAgent: 'node' };
for (const f of ['bridge.min.js', 'Kusto.Language.Bridge.min.js']) {
  vm.runInThisContext(fs.readFileSync(base + f, 'utf8'), { filename: f });
}
const S = Kusto.Language.Symbols;

const files = process.argv.slice(2);
const texts = files.map(f => fs.readFileSync(f, 'utf8'));

// The tables: the last definition of a name wins, as in the database.
const columns = new Map();
for (const text of texts) {
  for (const m of text.matchAll(/^\.create-merge table (\w+) \((.*)\)\s*$/gm)) columns.set(m[1], m[2]);
}
const tables = [...columns].map(([name, cols]) => S.TableSymbol.From('(' + cols + ')').WithName(name));
const database = new S.DatabaseSymbol.ctor('WindFarmEH', tables);
const globals = Kusto.Language.GlobalState.Default.WithDatabase(database);

// The stored functions.
const functions = [];
texts.forEach((text, i) => {
  const re = /^\.create-or-alter function with \([^\n]*?\) (\w+)\(([^)]*)\) \{\n([\s\S]*?)\n\}$/gm;
  for (const m of text.matchAll(re)) functions.push({ file: files[i], name: m[1], params: m[2], body: m[3] });
});
const asLet = fn => `let ${fn.name} = (${fn.params}) {\n${fn.body}\n};`;
function needed(body, seen = new Set()) {
  // the functions a query calls, and the ones those call, innermost first
  const out = [];
  for (const fn of functions) {
    if (seen.has(fn.name) || !new RegExp('\\b' + fn.name + '\\(').test(body)) continue;
    seen.add(fn.name);
    out.push(...needed(fn.body, seen), fn);
  }
  return out;
}

let checked = 0, failures = 0;
function check(label, prelude, body) {
  const text = (prelude ? prelude + '\n' : '') + body;
  const offset = prelude ? prelude.split('\n').length : 0;
  const list = Kusto.Language.KustoCode.ParseAndAnalyze(text, globals).GetDiagnostics();
  checked++;
  if (!list.Count) return;
  failures++;
  console.log(` PROBLEM in ${label}`);
  for (let i = 0; i < list.Count; i++) {
    const d = list.getItem ? list.getItem(i) : list.Items[i];
    const line = text.slice(0, d.Start).split('\n').length - offset;
    const where = line > 0 ? `line ${line} of it` : 'a function it calls';
    console.log(`  ${where}: [${d.Severity}] ${d.Message} near "${text.slice(d.Start, d.Start + Math.max(d.Length, 1)).slice(0, 50)}"`);
  }
}

for (const fn of functions) {
  // the parameters become variables, with their default or a value of their type
  const lets = fn.params.split(',').map(p => p.trim()).filter(Boolean).map(p => {
    const [name, rest] = p.split(':').map(x => x.trim());
    const [type, value] = rest.split('=').map(x => x.trim());
    const sample = { timespan: '1h', string: '""', datetime: 'now()', bool: 'true', real: '1.0' }[type] || '1';
    return `let ${name} = ${value || sample};`;
  });
  const calls = needed(fn.body, new Set([fn.name])).map(asLet);
  check(`${path.basename(fn.file)}, function ${fn.name}`, [...calls, ...lets].join('\n'), fn.body);
}

texts.forEach((text, i) => {
  const blocks = text.split(/\n\s*\n/).map(b => b.trim()).filter(Boolean);
  for (const block of blocks) {
    const body = block.split('\n').filter(l => !l.startsWith('//')).join('\n').trim();
    if (!body || body.startsWith('.')) continue;
    const prelude = needed(body).map(asLet).join('\n');
    check(`${path.basename(files[i])}, the block starting "${body.split('\n')[0].slice(0, 60)}"`, prelude, body);
  }
});

console.log(`${tables.length} tables, ${functions.length} stored functions, ${checked} functions and query blocks checked`);
console.log(failures ? `${failures} with diagnostics` : 'no diagnostics');
process.exit(failures ? 1 : 0);

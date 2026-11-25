// Opens the standalone preview in a headless browser and saves pictures of it, so that a change to the
// scene can be looked at. Needs Playwright and a Chrome or Chromium:
//   npm install --no-save playwright && npm run preview && npm run screenshots
// Environment: BROWSER_CHANNEL (default chrome), PLAYWRIGHT_MODULE (path of the module, if it is not
// installed here), SHOTS (output folder, default ./screenshots).
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright');
const out = path.resolve(process.env.SHOTS ?? path.join(here, 'screenshots'));
await mkdir(out, { recursive: true });

const browser = await chromium.launch({
  channel: process.env.BROWSER_CHANNEL ?? 'chrome',
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
});
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const problems = [];
page.on('console', (m) => m.type() === 'error' && problems.push(m.text()));
page.on('pageerror', (e) => problems.push(String(e)));

// `?fullquality` stops the twin from lowering its picture quality, which it would do on a software renderer.
await page.goto(`${pathToFileURL(path.join(here, 'preview', 'windfarm-twin-preview.html')).href}?fullquality`);
await page.waitForFunction(() => window.__twin !== undefined, undefined, { timeout: 60000 });
await page.evaluate(() => window.__twin.ready);
const shot = async (name, waitMs) => {
  await page.waitForTimeout(waitMs);
  await page.screenshot({ path: path.join(out, `${name}.png`) });
  console.log(`saved ${name}.png`);
};

await shot('1-site', 9000);
// Clicks go without waiting for the page to settle: a software renderer keeps it busy for seconds.
await page.click('.twin-fleet li:nth-child(7) button', { noWaitAfter: true }); // WT-07, the turbine with the warm gearbox
await shot('2-turbine', 9000);
// The turbine taken apart. Its parts move by the frame, and a software renderer takes its time over a frame.
await page.click('.twin-open', { noWaitAfter: true });
await page.waitForSelector('.twin-labels.parts-shown', { timeout: 120000 });
await page.click('.twin-chat header button', { noWaitAfter: true }); // without the chat the parts get the page
await shot('3-components', 16000);
await page.evaluate(() => {
  window.__preview.provider.injectFault('WT-07');
  window.__preview.advance(108); // the fault at its height: derated, four alarms on the gearbox
});
await shot('4-components-fault', 12000);
const parts = await page.evaluate(() => ({
  labels: [...document.querySelectorAll('.twin-part')].map((n) => `${n.dataset.part}:${n.dataset.level}`),
  rows: document.querySelectorAll('.twin-parts li').length,
  opened: window.__twin.openedTurbine,
}));
await page.click('.twin-chat-toggle', { noWaitAfter: true });
await page.click('.twin-open', { noWaitAfter: true });
await page.waitForFunction(() => document.querySelectorAll('.twin-part').length === 0, undefined, { timeout: 120000 });
await shot('5-fault', 9000);
await page.click('.twin-button', { noWaitAfter: true }); // whole site
await shot('6-site-with-fault', 9000);
// A limit on WT-03, as the operations agent sets one after an approval: the panel of the turbine says who asked.
await page.click('.twin-fleet li:nth-child(3) button', { noWaitAfter: true });
await page.evaluate(() => {
  window.__preview.advance(window.__preview.secondsToWind(11.2)); // a wind in which the limit holds the power down
  window.__preview.provider.limitTurbine('WT-03');
  window.__preview.advance(40); // the telemetry shows the limit and the power has come down
});
await page.waitForSelector('.twin-limit.command', { timeout: 120000 });
await shot('7-limit', 9000);
const limit = await page.evaluate(() => ({
  card: document.querySelector('.twin-limit')?.textContent ?? '',
  own: document.querySelectorAll('.twin-turbine .twin-commands li').length,
  kpi: [...document.querySelectorAll('.twin-kpi')].map((n) => n.textContent).find((t) => t.startsWith('Limited by command')) ?? '',
  // The controller's note about the limit is listed for the turbine. It is no alarm: not counted, no red mark.
  // The gearbox fault of the pictures before may still be active on WT-07, so the count is compared with the
  // list beside it and not with a fixed number.
  note: [...document.querySelectorAll('.twin-turbine .twin-alarms li.info')].map((n) => n.textContent).join(' | '),
  alarmsKpi: [...document.querySelectorAll('.twin-kpi')].map((n) => n.textContent).find((t) => t.startsWith('Active alarms')) ?? '',
  listed: [...document.querySelectorAll('.twin-alarmfeed .twin-alarms li')].map((n) => (n.classList.contains('info') ? 'note' : 'alarm')),
  redMarks: [...document.querySelectorAll('.twin-fleet .badge.alarm')].reduce((sum, n) => sum + Number(n.textContent), 0),
  redOnLimited: document.querySelectorAll('.twin-fleet li:nth-child(3) .badge.alarm').length,
}));
await page.click('.twin-button', { noWaitAfter: true }); // whole site
await page.click('.twin-tabs button:nth-child(2)', { noWaitAfter: true }); // the commands beside the alarms
await page.waitForSelector('.twin-alarmfeed .twin-commands li', { timeout: 120000 });
await shot('8-commands', 9000);
const feed = await page.evaluate(() => [...document.querySelectorAll('.twin-alarmfeed .twin-commands li')].map((n) => n.textContent));

const counts = await page.evaluate(() => ({
  labels: document.querySelectorAll('.twin-label').length,
  fleet: document.querySelectorAll('.twin-fleet li').length,
  canvas: document.querySelector('.twin-canvas')?.width ?? 0,
}));
await browser.close();
console.log(JSON.stringify({ ...counts, parts, limit, feed, problems }));
const partsRight = parts.labels.length === 11 && parts.rows === 11 && parts.opened === 'WT-07' && parts.labels.includes('GBX:2');
const listedAlarms = limit.listed.filter((kind) => kind === 'alarm').length;
const limitRight = limit.card.includes('Limited: 1,260 kW') && limit.card.includes('Asked by operations agent') && limit.own === 1 && limit.kpi.includes('1of 12')
  && limit.note.includes('POWER-CURTAILED') && limit.redOnLimited === 0 && limit.listed.includes('note')
  && limit.alarmsKpi === `Active alarms${listedAlarms}` && limit.redMarks === listedAlarms
  && !limit.listed.join(' ').includes('note alarm') // what is wrong comes first
  && feed.length === 1 && feed[0].includes('WT-03') && feed[0].includes('in force');
if (problems.length > 0 || counts.labels !== 15 || counts.fleet !== 12 || counts.canvas === 0 || !partsRight || !limitRight) process.exit(1);

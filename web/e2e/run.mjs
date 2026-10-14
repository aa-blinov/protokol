// Browser checks for the Протокол interface: upload, analysis, summaries by mode, layout.
//
// The run starts its own sidecar and a stub chat provider and keeps all data in a temporary
// folder, so it never reads or writes the app's own data.
//
//   E2E_AUDIO=/path/to/call.wav npm run e2e                  # API from api/ (its virtualenv)
//   E2E_TARGET=bundle E2E_AUDIO=/path/to/call.wav npm run e2e # sidecar inside desktop/release
//
// Optional: E2E_CHROME (browser executable, default Google Chrome), E2E_SHOTS (screenshot folder,
// default web/e2e/out). Needs web/dist built (npm run build) for the default target.
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';
import { bundledSidecar, freePort, startSidecar, startStub, waitForHealth } from './sidecar.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const audio = process.env.E2E_AUDIO;
const bundled = process.env.E2E_TARGET === 'bundle';
const chromePath = process.env.E2E_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const shots = process.env.E2E_SHOTS || path.join(here, 'out');

const results = [];
const consoleErrors = [];
const check = (name, ok, detail = '') => {
  results.push({ name, ok: Boolean(ok) });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`);
};

async function runChecks(browser, base, stubUrl) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, locale: 'ru-RU' });
  page.setDefaultTimeout(60000);
  page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message}`));
  const session = async () => (await (await fetch(`${base}/api/sessions`)).json())[0];
  const stubCalls = async () => (await (await fetch(stubUrl)).json()).count;
  const screen = () => page.evaluate(() => document.body.innerText || '');
  const shot = (name) => page.screenshot({ path: path.join(shots, name) });
  const panelOpen = () => page.locator('label', { hasText: 'Краткий пересказ' }).first().isVisible();
  const openPanel = async () => {
    if (!(await panelOpen())) await page.getByRole('button', { name: 'Изменить выжимку' }).click();
  };
  const chip = (label) => page.locator('button[aria-current]', { hasText: label }).first();
  const generate = page.getByRole('button', { name: 'Составить выжимку', exact: true });

  // 1. Empty history: the upload prompt is shown
  await page.goto(`${base}/`, { waitUntil: 'networkidle' });
  check('пустая история: приглашение загрузить запись', await page.getByText('Загрузите запись встречи').isVisible());
  await shot('01-empty.png');

  // 2. Upload: analysis, then the compose form
  await page.setInputFiles('input[type=file]', audio);
  await generate.waitFor({ timeout: 300000 });
  let text = await screen();
  check('анализ записи: найдены спикеры', /спикер/i.test(text));
  check('перед отправкой показан текст для модели', /что уйдёт в модель/i.test(text));
  await shot('02-analysed.png');

  // 3. First summary, default mode
  await generate.click();
  await page.getByText('ОТВЕТ-1', { exact: false }).first().waitFor({ timeout: 120000 });
  let stored = await session();
  check('первая выжимка показана на экране', (await screen()).includes('ОТВЕТ-1'));
  check('на диске одна выжимка', Object.keys(stored.summaries).length === 1, Object.keys(stored.summaries).join(','));
  await shot('03-summary-first-mode.png');

  // 4. Second mode through the compose panel; the panel closes once the summary is made
  await openPanel();
  await page.locator('label', { hasText: 'Договорённости сторон' }).click();
  await generate.click();
  await page.getByText('ОТВЕТ-2', { exact: false }).first().waitFor({ timeout: 120000 });
  await page.locator('label', { hasText: 'Краткий пересказ' }).waitFor({ state: 'detached', timeout: 10000 }).catch(() => {});
  stored = await session();
  check('вторая выжимка добавилась рядом с первой', Object.keys(stored.summaries).length === 2, Object.keys(stored.summaries).join(','));
  check('после выжимки панель «Изменить выжимку» закрылась', !(await panelOpen()));
  await shot('04-summary-second-mode.png');

  // 5. Mode chips bring up their own summary
  await chip('Решения и задачи').click();
  text = await screen();
  check('кнопка «Решения и задачи» показывает её выжимку', text.includes('ОТВЕТ-1') && !text.includes('ОТВЕТ-2'));
  await chip('Договорённости сторон').click();
  text = await screen();
  check('кнопка «Договорённости сторон» показывает её выжимку', text.includes('ОТВЕТ-2') && !text.includes('ОТВЕТ-1'));

  // 6. Compose panel: pick a third mode and leave with «Оставить как есть»: nothing changes
  const callsBefore = await stubCalls();
  await openPanel();
  await page.locator('label', { hasText: 'Краткий пересказ' }).click();
  await page.getByRole('button', { name: 'Оставить как есть' }).click();
  await page.waitForTimeout(500);
  text = await screen();
  stored = await session();
  const callsAfter = await stubCalls();
  check('«Оставить как есть»: на экране прежняя выжимка', text.includes('ОТВЕТ-2') && !text.includes('ОТВЕТ-1'));
  check('«Оставить как есть»: новых выжимок и обращений к модели нет',
    Object.keys(stored.summaries).length === 2 && callsAfter === callsBefore, `обращения ${callsBefore} → ${callsAfter}`);

  // 7. History rail stays in view while the document scrolls (desktop width; spacer only in the DOM)
  await page.evaluate(() => {
    const spacer = document.createElement('div');
    spacer.id = 'e2e-spacer';
    spacer.style.height = '2400px';
    document.querySelector('main').appendChild(spacer);
  });
  await page.evaluate(() => window.scrollTo(0, 800));
  await page.waitForTimeout(300);
  const rail = await page.evaluate(() => {
    const a = document.querySelector('aside.rail').getBoundingClientRect();
    const h = document.querySelector('header').getBoundingClientRect();
    return { top: Math.round(a.top), headerBottom: Math.round(h.bottom), bottom: Math.round(a.bottom), viewport: window.innerHeight, scrollY: window.scrollY };
  });
  check('история закреплена при прокрутке', Math.abs(rail.top - (rail.headerBottom + 24)) <= 2 && rail.bottom <= rail.viewport && rail.scrollY === 800, JSON.stringify(rail));
  await shot('05-rail-pinned.png');
  await page.evaluate(() => document.getElementById('e2e-spacer').remove());

  // 8. Dark theme
  await page.getByRole('button', { name: 'Тёмная тема' }).click();
  await page.waitForTimeout(300);
  check('тёмная тема включается', await page.evaluate(() => document.documentElement.classList.contains('dark')));
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);
  await shot('06-dark.png');

  // 9. Phone width: no horizontal scroll
  await page.setViewportSize({ width: 375, height: 812 });
  await page.waitForTimeout(400);
  const width = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  check('телефон 375px: нет горизонтальной прокрутки', width.scroll <= width.client, JSON.stringify(width));
  await shot('07-phone.png');

  // 10. Browser console
  check('в консоли браузера нет ошибок', consoleErrors.length === 0, consoleErrors.slice(0, 2).join(' | ').slice(0, 300));

  // 11. Stored state: both summaries on disk with their own replies
  stored = await session();
  const replies = Object.values(stored.summaries).map((item) => item.reply || '');
  check('на диске обе выжимки с текстом своих ответов', replies.some((t) => t.includes('ОТВЕТ-1')) && replies.some((t) => t.includes('ОТВЕТ-2')));
  console.log(`обращений к заглушке за прогон: ${await stubCalls()}`);
  await page.close();
}

async function main() {
  if (!audio || !existsSync(audio)) {
    console.error('Укажите запись: E2E_AUDIO=/path/to/call.wav npm run e2e');
    return 2;
  }
  if (!existsSync(chromePath)) {
    console.error(`Не найден браузер: ${chromePath} (задайте E2E_CHROME)`);
    return 2;
  }
  if (bundled && !existsSync(bundledSidecar)) {
    console.error('Собранного приложения нет: сначала desktop/build.sh --mac');
    return 2;
  }
  const dataDir = mkdtempSync(path.join(os.tmpdir(), 'protokol-e2e-'));
  writeFileSync(path.join(dataDir, '.env'), '');
  mkdirSync(shots, { recursive: true });
  const stub = await startStub(await freePort());
  const stubUrl = `http://127.0.0.1:${stub.address().port}`;
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const sidecar = startSidecar({ port, envFile: path.join(dataDir, '.env'), stubUrl, bundled });
  const sidecarLog = [];
  sidecar.stdout.on('data', (chunk) => sidecarLog.push(chunk.toString()));
  sidecar.stderr.on('data', (chunk) => sidecarLog.push(chunk.toString()));
  let browser = null;
  try {
    await waitForHealth(base);
    browser = await chromium.launch({ executablePath: chromePath, headless: true });
    await runChecks(browser, base, stubUrl);
  } catch (error) {
    console.error('E2E остановлен:', String(error.message || error).slice(0, 400));
    console.error(sidecarLog.join('').split('\n').slice(-20).join('\n'));
    return 2;
  } finally {
    if (browser) await browser.close().catch(() => {});
    sidecar.kill('SIGTERM');
    stub.close();
    rmSync(dataDir, { recursive: true, force: true });
  }
  const failed = results.filter((result) => !result.ok);
  console.log(`\n${results.length - failed.length} из ${results.length} проверок прошли`);
  return failed.length ? 1 : 0;
}

process.exitCode = await main();

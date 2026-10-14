// Screenshots for the README, taken from the current build with an invented meeting
// (web/e2e/demo/sessions.json: no real people, numbers or places).
//
//   npm run shots                         # writes docs/screenshots
//   SHOTS_OUT=/some/folder npm run shots  # any other folder
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';
import { freePort, startSidecar, waitForHealth } from './sidecar.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '..', '..');
const out = process.env.SHOTS_OUT || path.join(repo, 'docs/screenshots');
const chromePath = process.env.E2E_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const demo = JSON.parse(readFileSync(path.join(here, 'demo/sessions.json'), 'utf-8'));
const desktop = { viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2, locale: 'ru-RU' };
const phone = { viewport: { width: 480, height: 900 }, deviceScaleFactor: 2, locale: 'ru-RU' };
const session = 'казначейство.wav';

async function capture(browser, base) {
  const save = (page, name, options = {}) => page.screenshot({ path: path.join(out, name), ...options });
  const open = async (page) => {
    await page.goto(`${base}/`, { waitUntil: 'networkidle' });
    await page.locator('li button', { hasText: session }).first().click();
    await page.getByText('Кредитная линия', { exact: false }).first().waitFor();
  };
  const setTheme = async (page, dark) => {
    const isDark = await page.evaluate(() => document.documentElement.classList.contains('dark'));
    if (isDark !== dark) await page.locator('button[aria-label="Тёмная тема"], button[aria-label="Светлая тема"]').first().click();
    await page.waitForTimeout(200);
  };
  const openSettings = async (page) => {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.getByRole('button', { name: 'Настройки' }).click();
    await page.locator('#settings-panel').waitFor();
    await page.waitForTimeout(300);
  };

  // Empty history, before the invented meeting is loaded
  const mobile = await browser.newContext(phone);
  const mobilePage = await mobile.newPage();
  await mobilePage.goto(`${base}/`, { waitUntil: 'networkidle' });
  await save(mobilePage, 'app-empty-mobile.png');
  await mobile.close();

  const context = await browser.newContext(desktop);
  const page = await context.newPage();
  await page.goto(`${base}/`, { waitUntil: 'networkidle' });
  await save(page, 'app-empty.png');

  const put = await fetch(`${base}/api/sessions`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(demo),
  });
  if (!put.ok) throw new Error(`демо-история не записалась: ${put.status}`);

  // Light theme: document, transcript, search, settings, history
  await open(page);
  await save(page, 'app-results.png');

  await page.getByText('Здравствуйте. Я Иван', { exact: false }).first()
    .evaluate((element) => element.scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(200);
  await save(page, 'app-diarization.png');

  await page.evaluate(() => window.scrollTo(0, 0));
  const search = page.locator('input[aria-label="Поиск по расшифровке"]');
  await search.fill('казначейства');
  await page.waitForTimeout(300);
  await save(page, 'app-search.png');
  await search.fill('');

  await openSettings(page);
  await save(page, 'app-settings.png', { fullPage: true });

  await open(page);
  await page.getByRole('button', { name: `Переименовать запись ${session}` }).click();
  await page.waitForTimeout(200);
  await save(page, 'app-history.png');

  // Dark theme: document and settings
  await open(page);
  await setTheme(page, true);
  await save(page, 'app-dark-results.png');
  await openSettings(page);
  await save(page, 'app-dark-settings.png', { fullPage: true });

  await context.close();
}

async function main() {
  if (!existsSync(chromePath)) {
    console.error(`Не найден браузер: ${chromePath} (задайте E2E_CHROME)`);
    return 2;
  }
  mkdirSync(out, { recursive: true });
  const dataDir = mkdtempSync(path.join(os.tmpdir(), 'protokol-shots-'));
  writeFileSync(path.join(dataDir, '.env'), '');
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const sidecar = startSidecar({ port, envFile: path.join(dataDir, '.env'), });
  let browser = null;
  try {
    await waitForHealth(base);
    browser = await chromium.launch({ executablePath: chromePath, headless: true });
    await capture(browser, base);
    console.log(`снимки записаны: ${out}`);
    return 0;
  } catch (error) {
    console.error('Снимки не сделаны:', String(error.message || error).slice(0, 400));
    return 2;
  } finally {
    if (browser) await browser.close().catch(() => {});
    sidecar.kill('SIGTERM');
    rmSync(dataDir, { recursive: true, force: true });
  }
}

process.exitCode = await main();

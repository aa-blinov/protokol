// Start-up shared by the browser checks and the screenshot run: a free port, the sidecar (the API
// from api/, or the one inside the built app) and, when asked for, a stand-in chat provider.
// Everything listens on 127.0.0.1 and keeps its data in the folder it is given.
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const resources = path.join(repo, 'desktop/release/mac-arm64/sttshka.app/Contents/Resources');
export const bundledSidecar = path.join(resources, 'sidecar/sttshka-api/sttshka-api');

export function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.on('error', reject);
    probe.listen(0, '127.0.0.1', () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

// Every chat call gets the next number, so the answers can be told apart on screen.
// A GET returns how many calls it has answered.
export function startStub(port) {
  let calls = 0;
  const server = createServer((req, res) => {
    if (req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ count: calls }));
      return;
    }
    req.resume();
    req.on('end', () => {
      calls += 1;
      const reply = `ОТВЕТ-${calls}: проверочная выжимка без реальных данных.`;
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({
        model: 'test/model',
        choices: [{ message: { role: 'assistant', content: reply }, finish_reason: 'stop' }],
        usage: { prompt_tokens: 11, completion_tokens: 22 },
      }));
    });
  });
  return new Promise((resolve) => server.listen(port, '127.0.0.1', () => resolve(server)));
}

// The sidecar takes its service and key from OPENROUTER_* first, so the user's own values are
// dropped here. A stub URL, when given, replaces them.
export function startSidecar({ port, envFile, stubUrl = null, bundled = false }) {
  const env = { ...process.env, HOST: '127.0.0.1', PORT: String(port), STTSHKA_ENV_FILE: envFile };
  for (const name of Object.keys(env)) {
    if (name.startsWith('OPENROUTER_')) delete env[name];
  }
  if (stubUrl) {
    env.OPENROUTER_BASE_URL = `${stubUrl}/v1`;
    env.OPENROUTER_API_KEY = 'stub-key-for-local-test';
  }
  const stdio = ['ignore', 'pipe', 'pipe'];
  if (bundled) {
    return spawn(bundledSidecar, [], {
      cwd: resources,
      stdio,
      env: { ...env, MODELS_DIR: path.join(resources, 'models'), WEB_DIST_DIR: path.join(resources, 'web') },
    });
  }
  return spawn(path.join(repo, 'api/.venv/bin/uvicorn'), ['main:app', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: path.join(repo, 'api'),
    stdio,
    env,
  });
}

export async function waitForHealth(base, timeoutMs = 180000) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    try {
      if ((await fetch(`${base}/api/health`)).ok) return;
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`сайдкар не ответил за ${timeoutMs / 1000} с`);
}

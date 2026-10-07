/**
 * Desktop shell: spawns the Python sidecar on a free local port and shows its UI.
 *
 * The sidecar is a FastAPI process that serves both the API and the built web UI
 * from 127.0.0.1, so the window is a plain local page — no CORS, no proxy, and
 * nothing listens outside the machine.
 */
const { app, BrowserWindow, dialog } = require("electron");
const { spawn } = require("node:child_process");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

const STARTUP_TIMEOUT_MS = 120_000; // first run compiles/loads ONNX models
const HEALTH_PATH = "/api/health";

let sidecar = null;
let sidecarLog = "";

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.unref();
    probe.on("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

function waitForHealth(port, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const request = http.get({ host: "127.0.0.1", port, path: HEALTH_PATH, timeout: 3000 }, (response) => {
        response.resume();
        if (response.statusCode === 200) return resolve();
        retry();
      });
      request.on("error", retry);
      request.on("timeout", () => {
        request.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() > deadline) {
        return reject(new Error(`Сервер не ответил за ${Math.round(timeoutMs / 1000)} с`));
      }
      setTimeout(attempt, 500);
    };
    attempt();
  });
}

/** Sidecar as a packaged binary, or straight from source during development. */
function sidecarCommand() {
  if (app.isPackaged) {
    // PyInstaller onedir: resources/sidecar/sttshka-api/{sttshka-api,_internal/}
    const exe = process.platform === "win32" ? "sttshka-api.exe" : "sttshka-api";
    return {
      command: path.join(process.resourcesPath, "sidecar", "sttshka-api", exe),
      args: [],
      cwd: path.join(process.resourcesPath, "sidecar", "sttshka-api"),
    };
  }
  return {
    command: process.env.STTSHKA_PYTHON || "python3",
    args: [path.join(__dirname, "..", "api", "main.py")],
    cwd: path.join(__dirname, "..", "api"),
  };
}

function sidecarEnv(port) {
  const env = { ...process.env, HOST: "127.0.0.1", PORT: String(port) };
  if (!env.MODELS_DIR) {
    // Models ship inside the bundle so the app is self-contained and relocatable.
    env.MODELS_DIR = app.isPackaged
      ? path.join(process.resourcesPath, "models")
      : path.join(__dirname, "..", "models");
  }
  if (!env.WEB_DIST_DIR) {
    env.WEB_DIST_DIR = app.isPackaged
      ? path.join(process.resourcesPath, "web")
      : path.join(__dirname, "..", "web", "dist");
  }
  if (!env.STTSHKA_ENV_FILE) {
    // Secrets live outside the bundle — never packaged, never in git. A
    // double-clicked app inherits no shell env, so the sidecar reads them here.
    env.STTSHKA_ENV_FILE = app.isPackaged
      ? path.join(app.getPath("userData"), ".env")
      : path.join(__dirname, "..", ".env");
  }
  return env;
}

function stopSidecar() {
  if (sidecar && sidecar.exitCode === null) {
    sidecar.kill("SIGTERM");
    sidecar = null;
  }
}

async function createWindow() {
  const port = await freePort();
  const { command, args, cwd } = sidecarCommand();

  sidecar = spawn(command, args, { cwd, env: sidecarEnv(port), stdio: ["ignore", "pipe", "pipe"] });
  const record = (chunk) => {
    sidecarLog = (sidecarLog + chunk.toString()).slice(-8000);
  };
  sidecar.stdout.on("data", record);
  sidecar.stderr.on("data", record);
  sidecar.on("exit", (code) => {
    if (code !== 0 && code !== null) {
      dialog.showErrorBox("Сервер обработки завершился", `Код ${code}\n\n${sidecarLog.slice(-2000)}`);
    }
    sidecar = null;
    app.quit();
  });

  try {
    await waitForHealth(port, STARTUP_TIMEOUT_MS);
  } catch (error) {
    stopSidecar();
    dialog.showErrorBox("Не удалось запустить обработку", `${error.message}\n\n${sidecarLog.slice(-2000)}`);
    app.quit();
    return;
  }

  console.log(`[sttshka] sidecar ready on http://127.0.0.1:${port}`);

  const window = new BrowserWindow({
    width: 1280,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    title: "STT → PII → OpenRouter",
    // The UI is our own local page; keep node out of it.
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });

  await window.loadURL(`http://127.0.0.1:${port}`);
}

app.on("window-all-closed", () => {
  stopSidecar();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", stopSidecar);

app.whenReady().then(() => {
  createWindow().catch((error) => {
    dialog.showErrorBox("Не удалось запустить приложение", String(error?.message ?? error));
    app.quit();
  });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, rmSync, statSync, copyFileSync, chmodSync, realpathSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

const scriptPath = fileURLToPath(import.meta.url);
const sourceRoot = resolve(dirname(scriptPath), "..");

const DEFAULT_INSTALL_DIR = join(homedir(), ".beeclaw-radar");
const INSTALL_MARKER = ".beeclaw-radar-install";
const EXCLUDED = new Set([
  ".git",
  ".DS_Store",
  ".env",
  ".external",
  ".chrome-webbridge-profile",
  "data",
  "dist",
  "feishu_workspace",
  "output",
  "reports",
  "weekly-market-report",
  "__pycache__",
  ".pytest_cache"
]);

function usage() {
  console.log(`Beeclaw Radar npx installer

Usage:
  npx beeclaw-radar [action] [options]
  npx github:Zanetach/radar-claw [action] [options]

Actions:
  install     Copy package to install dir, install dependencies, and start Radar API. Default.
  doctor      Run installed ./tools/install_beeclaw.sh doctor.
  start-api   Run installed Radar API in the foreground.
  path        Print install directory.

Options:
  --dir PATH       Install directory. Default: ${DEFAULT_INSTALL_DIR}
  --base-url URL   Radar API URL passed to installer. Default: http://127.0.0.1:8780.
  --venv PATH      Python venv path passed to installer.
  --skip-hermes    Skip Hermes config during install.
  --skip-clis      Skip bundled CLI backend install during install.
  --no-start       Install only; do not start the Radar API service.
  -h, --help       Show this help.

Examples:
  npx github:Zanetach/radar-claw install
  npx github:Zanetach/radar-claw doctor
  npx github:Zanetach/radar-claw start-api
`);
}

function parseArgs(argv) {
  const result = {
    action: "install",
    installDir: process.env.BEECLAW_INSTALL_DIR || DEFAULT_INSTALL_DIR,
    passThrough: []
  };
  const args = [...argv];
  if (args[0] && !args[0].startsWith("-")) {
    result.action = args.shift();
  }
  while (args.length) {
    const arg = args.shift();
    if (arg === "--dir") {
      result.installDir = resolve(args.shift() || "");
    } else if (arg === "--base-url" || arg === "--venv") {
      result.passThrough.push(arg, args.shift() || "");
    } else if (arg === "--skip-hermes" || arg === "--skip-clis" || arg === "--no-start") {
      result.passThrough.push(arg);
    } else if (arg === "-h" || arg === "--help") {
      result.action = "help";
    } else {
      console.error(`Unknown argument: ${arg}`);
      process.exit(2);
    }
  }
  return result;
}

function shouldSkip(name, absolutePath) {
  if (EXCLUDED.has(name)) return true;
  if (name.endsWith(".pyc")) return true;
  const rel = relative(sourceRoot, absolutePath);
  return rel === "tools/xmcp/.env" || rel.startsWith("tools/xmcp/.env/");
}

function copyTree(src, dest) {
  const base = basename(src);
  if (shouldSkip(base, src)) return;
  const stats = statSync(src);
  if (stats.isDirectory()) {
    mkdirSync(dest, { recursive: true });
    for (const child of readdirSync(src)) {
      copyTree(join(src, child), join(dest, child));
    }
  } else if (stats.isSymbolicLink()) {
    // Keep installer deterministic and avoid copying links outside the package.
    return;
  } else if (stats.isFile()) {
    mkdirSync(dirname(dest), { recursive: true });
    copyFileSync(src, dest);
    if (stats.mode & 0o111) chmodSync(dest, stats.mode);
  }
}

function samePath(a, b) {
  try {
    return realpathSync(a) === realpathSync(b);
  } catch {
    return resolve(a) === resolve(b);
  }
}

function isEmptyDir(path) {
  return existsSync(path) && statSync(path).isDirectory() && readdirSync(path).length === 0;
}

function isManagedInstallDir(path) {
  if (!existsSync(path)) return true;
  if (!statSync(path).isDirectory()) return false;
  if (isEmptyDir(path)) return true;
  if (existsSync(join(path, INSTALL_MARKER))) return true;
  const packagePath = join(path, "package.json");
  if (!existsSync(packagePath)) return false;
  try {
    const payload = JSON.parse(readFileSync(packagePath, "utf8"));
    return payload && payload.name === "beeclaw-radar";
  } catch {
    return false;
  }
}

function assertSafeInstallDir(installDir) {
  const resolved = resolve(installDir);
  const unsafeRoots = new Set([resolve("/"), homedir(), resolve(dirname(homedir()))]);
  if (unsafeRoots.has(resolved)) {
    console.error(`Refusing to use unsafe install directory: ${resolved}`);
    process.exit(1);
  }
  if (existsSync(resolved) && !samePath(sourceRoot, resolved) && !isManagedInstallDir(resolved)) {
    console.error(`Refusing to overwrite non-Beeclaw directory: ${resolved}`);
    console.error("Choose an empty directory, remove it manually, or use the default ~/.beeclaw-radar path.");
    process.exit(1);
  }
}

function syncPackageToInstallDir(installDir) {
  assertSafeInstallDir(installDir);
  mkdirSync(dirname(installDir), { recursive: true });
  if (existsSync(installDir) && !samePath(sourceRoot, installDir)) {
    rmSync(installDir, { recursive: true, force: true });
  }
  if (!samePath(sourceRoot, installDir)) {
    mkdirSync(installDir, { recursive: true });
    for (const child of readdirSync(sourceRoot)) {
      copyTree(join(sourceRoot, child), join(installDir, child));
    }
    writeFileSync(join(installDir, INSTALL_MARKER), "managed by beeclaw-radar npx installer\n", "utf8");
  }
}

function runScript(installDir, action, passThrough) {
  const script = join(installDir, "tools", "install_beeclaw.sh");
  if (!existsSync(script)) {
    console.error(`Missing installer: ${script}`);
    process.exit(1);
  }
  const args = [script];
  if (action === "doctor" || action === "start-api") args.push(action);
  args.push(...passThrough);
  const result = spawnSync("bash", args, {
    cwd: installDir,
    stdio: "inherit",
    env: process.env
  });
  process.exit(result.status ?? 1);
}

const parsed = parseArgs(process.argv.slice(2));

if (parsed.action === "help") {
  usage();
  process.exit(0);
}

if (parsed.action === "path") {
  console.log(parsed.installDir);
  process.exit(0);
}

if (!["install", "doctor", "start-api"].includes(parsed.action)) {
  console.error(`Unknown action: ${parsed.action}`);
  usage();
  process.exit(2);
}

if (parsed.action === "install") {
  console.log(`[beeclaw-npx] Installing package to ${parsed.installDir}`);
  syncPackageToInstallDir(parsed.installDir);
  runScript(parsed.installDir, "install", parsed.passThrough);
} else {
  if (!existsSync(parsed.installDir)) {
    console.error(`Install directory does not exist: ${parsed.installDir}`);
    console.error("Run: npx beeclaw-radar install");
    process.exit(1);
  }
  runScript(parsed.installDir, parsed.action, parsed.passThrough);
}

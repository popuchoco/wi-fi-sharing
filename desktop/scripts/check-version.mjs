import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const readJson = relativePath => JSON.parse(readFileSync(resolve(desktopRoot, relativePath), "utf8"));
const expectedPackages = ["wifi-core", "wifi-platform", "wifi-sharing-desktop"];

const metadata = spawnSync(
  process.env.CARGO || "cargo",
  ["metadata", "--locked", "--no-deps", "--format-version", "1"],
  { cwd: desktopRoot, encoding: "utf8", windowsHide: true }
);

if (metadata.error) throw metadata.error;
if (metadata.status !== 0) {
  process.stderr.write(metadata.stderr || "cargo metadata failed.\n");
  process.exit(metadata.status || 1);
}

const cargoPackages = new Map(
  JSON.parse(metadata.stdout).packages.map(({ name, version }) => [name, version])
);
const versions = new Map([
  ["package.json", readJson("package.json").version],
  ["package-lock.json", readJson("package-lock.json").packages?.[""]?.version],
  ["tauri.conf.json", readJson("src-tauri/tauri.conf.json").version],
  ...expectedPackages.map(name => [`Cargo package ${name}`, cargoPackages.get(name)])
]);

const missing = [...versions].filter(([, version]) => !version);
if (missing.length) {
  throw new Error(`Missing version metadata: ${missing.map(([name]) => name).join(", ")}`);
}

const distinctVersions = new Set(versions.values());
if (distinctVersions.size !== 1) {
  const details = [...versions].map(([name, version]) => `  ${name}: ${version}`).join("\n");
  throw new Error(`Desktop version mismatch:\n${details}`);
}

console.log(`Desktop versions aligned: ${[...distinctVersions][0]}`);

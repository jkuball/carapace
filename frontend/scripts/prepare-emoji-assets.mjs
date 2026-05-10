import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { execFileSync } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendRoot = path.resolve(__dirname, "..");
const publicEmojiDir = path.join(frontendRoot, "public", "emoji");
const TWEMOJI_VERSION = "17.0.2";
const TWEMOJI_GH_PAGES_COMMIT = "40c2213";
const TWEMOJI_ARCHIVE_URL = `https://codeload.github.com/jdecked/twemoji/tar.gz/${TWEMOJI_GH_PAGES_COMMIT}`;
const TWEMOJI_CACHE_DIR = path.join(
  frontendRoot,
  "node_modules",
  ".cache",
  `twemoji-${TWEMOJI_GH_PAGES_COMMIT}`,
);
const TWEMOJI_EXTRACTED_DIR = path.join(
  TWEMOJI_CACHE_DIR,
  `twemoji-${TWEMOJI_GH_PAGES_COMMIT}`,
);
const CANDIDATE_SOURCE_DIRS = [
  path.join(TWEMOJI_EXTRACTED_DIR, "v", TWEMOJI_VERSION, "svg"),
  path.join(TWEMOJI_EXTRACTED_DIR, "svg"),
  path.join(frontendRoot, "node_modules", "@twemoji", "svg"),
  path.join(
    frontendRoot,
    "node_modules",
    "jdecked-twemoji-assets",
    "assets",
    "svg",
  ),
];
const generatedFilePath = path.join(
  frontendRoot,
  "src",
  "lib",
  "emoji.generated.ts",
);

const sourceDir = await resolveSourceDir();

rmSync(publicEmojiDir, { force: true, recursive: true });

mkdirSync(publicEmojiDir, { recursive: true });

const svgFiles = collectSvgFiles(sourceDir);
const copied = new Set();

for (const filePath of svgFiles) {
  const fileName = path.basename(filePath).toLowerCase();
  const targetPath = path.join(publicEmojiDir, fileName);
  if (copied.has(fileName)) {
    continue;
  }
  cpSync(filePath, targetPath);
  copied.add(fileName);
}

writeGeneratedModule({
  codepoints: Array.from(copied, (fileName) => fileName.slice(0, -4)).sort(),
});

process.stdout.write(
  `Prepared bundled Twemoji assets with ${copied.size} SVG files.\n`,
);

async function resolveSourceDir() {
  for (const candidateDir of CANDIDATE_SOURCE_DIRS) {
    if (existsSync(candidateDir)) {
      return candidateDir;
    }
  }

  await downloadTwemojiAssets();

  for (const candidateDir of CANDIDATE_SOURCE_DIRS) {
    if (existsSync(candidateDir)) {
      return candidateDir;
    }
  }

  throw new Error(
    `Twemoji SVG assets were not found after downloading ${TWEMOJI_ARCHIVE_URL}.`,
  );
}

async function downloadTwemojiAssets() {
  const tmpDir = mkdtempSync(path.join(os.tmpdir(), "twemoji-"));
  const archivePath = path.join(tmpDir, `${TWEMOJI_GH_PAGES_COMMIT}.tar.gz`);

  rmSync(TWEMOJI_CACHE_DIR, { force: true, recursive: true });
  mkdirSync(TWEMOJI_CACHE_DIR, { recursive: true });

  try {
    const response = await fetch(TWEMOJI_ARCHIVE_URL);
    if (!response.ok) {
      throw new Error(
        `Failed to download Twemoji assets: ${response.status} ${response.statusText}`,
      );
    }

    writeFileSync(archivePath, Buffer.from(await response.arrayBuffer()));
    execFileSync("tar", ["-xzf", archivePath, "-C", TWEMOJI_CACHE_DIR]);
  } finally {
    rmSync(tmpDir, { force: true, recursive: true });
  }
}

function collectSvgFiles(dirPath) {
  const entries = readdirSync(dirPath, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const entryPath = path.join(dirPath, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectSvgFiles(entryPath));
      continue;
    }

    if (entry.isFile() && entry.name.endsWith(".svg")) {
      files.push(entryPath);
    }
  }

  return files;
}

function writeGeneratedModule({ codepoints }) {
  const contents = `export const emojiSet = "twemoji" as const;\n\nexport const bundledEmojiCodepoints = ${JSON.stringify(codepoints, null, 2)} as const;\n`;
  writeFileSync(generatedFilePath, contents);
}

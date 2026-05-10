import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { NextConfig } from "next";

function readCarapaceVersion(): string {
  const configuredVersion = process.env.NEXT_PUBLIC_CARAPACE_VERSION?.trim();
  if (configuredVersion) {
    return configuredVersion;
  }

  const packageJsonPath = resolve(process.cwd(), "package.json");
  const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf8")) as {
    version?: unknown;
  };
  return typeof packageJson.version === "string" && packageJson.version.trim()
    ? packageJson.version.trim()
    : "dev";
}

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_CARAPACE_VERSION: readCarapaceVersion(),
  },
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The monorepo root has its own package-lock.json, so Turbopack otherwise
  // infers the workspace root as the repo and warns. This app is self-contained.
  turbopack: { root: __dirname },
  // Next 16 writes its own AGENTS.md and CLAUDE.md into the app on dev start.
  // The repo already has a CLAUDE.md at the root and a nested one would shadow
  // it for anything working in this directory.
  agentRules: false,
};

export default nextConfig;

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Next 16 writes AGENTS.md/CLAUDE.md into the project on dev start; the pilot
  // repository controls its own documentation set.
  agentRules: false,
  poweredByHeader: false,
  compress: true,
};
export default nextConfig;

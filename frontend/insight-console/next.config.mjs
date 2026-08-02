// Insight Console — Next.js config.
//
// Sprint 8: strict prod posture. Source maps in prod, no telemetry,
// no image domains exposed (Console renders no user-uploaded media —
// avatars/posts live in the mobile app).

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || "",
  productionBrowserSourceMaps: true,
  poweredByHeader: false,
  // V1.2 packaging: self-contained server bundle for the Docker image
  // (node .next/standalone/server.js — no node_modules in the image).
  output: "standalone",
  // Brand assets are static local PNGs; skip the optimizer (no sharp needed
  // in the standalone image). The console renders no user media.
  images: { unoptimized: true },
  // Console is server-rendered. Atrium's URL is fetched server-side
  // via process.env; browser code uses our /api BFF proxy only.
  experimental: {
    serverComponentsExternalPackages: ["jose", "pg"],
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Strict-Transport-Security",
            value: "max-age=31536000; includeSubDomains; preload",
          },
          { key: "Permissions-Policy", value: "geolocation=(), microphone=(), camera=()" },
        ],
      },
    ];
  },
};

export default nextConfig;

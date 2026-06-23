/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Proxy /api/* to the ZeroWall Core API so the browser avoids CORS and the
  // backend host is configurable per environment (compose, DGX, localhost).
  async rewrites() {
    const target = process.env.ZEROWALL_API_URL || "http://localhost:9000";
    return [{ source: "/api/:path*", destination: `${target}/:path*` }];
  },
};

export default nextConfig;

import type { NextConfig } from "next";

const DJANGO_INTERNAL_URL = "http://127.0.0.1:8010";

const nextConfig: NextConfig = {
  trailingSlash: true,

  async rewrites() {
    return [
      {
        source: "/api/v1/:path*/",
        destination: `${DJANGO_INTERNAL_URL}/api/v1/:path*/`,
      },
    ];
  },
};

export default nextConfig;
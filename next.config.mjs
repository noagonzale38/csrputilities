const backend = process.env.NEXT_PUBLIC_BACKEND_ORIGIN || "http://127.0.0.1:4000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      { source: "/api/dashboard", destination: `${backend}/api/dashboard` },
      { source: "/api/session", destination: `${backend}/api/session` },
      { source: "/api/themes", destination: `${backend}/api/themes` },
      { source: "/api/themes/:path*", destination: `${backend}/api/themes/:path*` },
      { source: "/api/login", destination: `${backend}/login` },
      { source: "/api/logout", destination: `${backend}/logout` },
      { source: "/api/auth/callback", destination: `${backend}/auth/callback` },
      { source: "/api/actions/:path*", destination: `${backend}/actions/:path*` },
      { source: "/actions/:path*", destination: `${backend}/actions/:path*` },
      { source: "/auth/callback", destination: `${backend}/auth/callback` }
    ];
  }
};

export default nextConfig;

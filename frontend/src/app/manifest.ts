import type { MetadataRoute } from "next";

export const dynamic = "force-static";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "carapace",
    short_name: "carapace",
    description: "Security-first personal AI agent",
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#236b86",
    icons: [
      {
        src: "/pwa-192x192.png",
        sizes: "192x192",
        type: "image/png",
      },
      {
        src: "/pwa-512x512.png",
        sizes: "512x512",
        type: "image/png",
      },
    ],
  };
}

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/static/ui/",
  build: {
    manifest: true,
    rollupOptions: {
      input: "src/main.jsx",
      output: {
        manualChunks(id) {
          if (id.includes("node_modules"))
            return /node_modules\/(react|react-dom|scheduler)\//.test(
              id.replaceAll("\\", "/"),
            )
              ? "react"
              : "material";
        },
      },
    },
  },
});

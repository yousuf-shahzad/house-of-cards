import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  server: {
    // Backend routes only: a bare "/api" would also catch source files in ./api/.
    proxy: { "^/api/(health|analysis|examples|etfs)(/|$)": "http://127.0.0.1:8000" },
  },
});

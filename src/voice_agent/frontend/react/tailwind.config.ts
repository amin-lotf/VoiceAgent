import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        shell: "#080b11",
        panel: "#10151d",
        line: "#202a36",
        accent: "#3dd9b8",
        info: "#60a5fa",
        warn: "#f59e0b",
        danger: "#f87171",
      },
      boxShadow: {
        panel: "0 18px 40px rgba(2, 6, 23, 0.28)",
      },
    },
  },
  plugins: [],
} satisfies Config;

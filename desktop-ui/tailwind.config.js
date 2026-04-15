/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "#ffffff",
          2: "#e8ecf2",
        },
        accent: {
          DEFAULT: "#2563eb",
          2: "#6d28d9",
        },
        text: {
          DEFAULT: "#1c2333",
          2: "#5a6578",
        },
      },
      fontFamily: {
        mono: ['"Cascadia Code"', '"Fira Code"', "monospace"],
      },
    },
  },
  plugins: [],
};

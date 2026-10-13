
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bn: {
          dark: "#0B0F17",
          card: "#131B2E",
          cardHover: "#1A253D",
          border: "#1E2B45",
          green: "#22C55E",
          greenHover: "#16A34A",
          gold: "#F59E0B",
          goldHover: "#D97706",
          blue: "#3B82F6",
          blueHover: "#2563EB",
          muted: "#94A3B8",
        }
      },
      boxShadow: {
        'glow-green': '0 0 20px -5px rgba(34, 197, 94, 0.4)',
        'glow-blue': '0 0 20px -5px rgba(59, 130, 246, 0.4)',
      }
    },
  },
  plugins: [],
}
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./**/templates/**/*.html",
    "./**/static/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Quicksand"', 'Segoe UI', 'Tahoma', 'Geneva', 'Verdana', 'sans-serif'],
        mono: ['ui-monospace', 'Cascadia Code', 'Segoe UI Mono', 'Menlo', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}


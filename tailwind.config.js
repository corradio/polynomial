/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './.venv/lib/**/templates/**/*.html',
    './node_modules/flowbite/**/*.js',
  ],
  theme: {
    extend: {},
  },
  plugins: [
    require('flowbite/plugin'),
    require('@tailwindcss/forms'),
    require('tailwind-scrollbar-hide'),
  ],
  safelist: [
    'errorlist', // used by django form utils
  ],
}

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './.venv/lib/**/templates/**/*.html',
    './node_modules/flowbite/**/*.js',
    './.venv/lib/**/django_jsonform/react-json-form.js',
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
    'text-green-500', // used in metric_mosaic
  ],
}

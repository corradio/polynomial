/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './mainapp/templates/**/*.html',
    './node_modules/flowbite/**/*.js',
  ],
  theme: {
    extend: {},
  },
  plugins: [require('flowbite/plugin')],
}

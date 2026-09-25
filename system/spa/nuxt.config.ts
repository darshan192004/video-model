// Static client-side app (ssr:false): Nuxt prerenders the route shells, the
// browser hydrates them, and the control-plane serves `dist/` verbatim at "/".
export default defineNuxtConfig({
  ssr: false,
  srcDir: "app",
  devtools: { enabled: false },
  app: {
    baseURL: "/",
    head: {
      htmlAttrs: { lang: "en" },
      title: "Media Studio",
      meta: [
        { name: "viewport", content: "width=device-width, initial-scale=1" },
        { name: "theme-color", content: "#0b1020" },
      ],
    },
  },
  nitro: {
    preset: "static",
    output: { publicDir: "dist" },
  },
  imports: {
    dirs: ["stores"],
  },
  css: ["~/assets/main.css"],
  typescript: {
    strict: true,
    typeCheck: false,
  },
})
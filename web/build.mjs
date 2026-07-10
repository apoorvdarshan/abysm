import { cp, mkdir, rm } from "node:fs/promises";

const outputDirectory = new URL("./dist/", import.meta.url);
const entries = [
  "404.html",
  "assets",
  "fonts",
  "index.html",
  "main.js",
  "robots.txt",
  "sitemap.xml",
  "styles.css",
];

await rm(outputDirectory, { recursive: true, force: true });
await mkdir(outputDirectory, { recursive: true });

for (const entry of entries) {
  await cp(new URL(entry, import.meta.url), new URL(entry, outputDirectory), {
    recursive: true,
  });
}

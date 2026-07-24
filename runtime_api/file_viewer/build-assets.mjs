import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageEntry = fileURLToPath(import.meta.resolve("@file-viewer/web-full"));
const sourceRoot = path.dirname(packageEntry);
const outputRoot = path.resolve(process.argv[2] || "../app/static/vendor/file-viewer");

const rendererNames = ["image", "pdf", "word", "presentation", "spreadsheet", "text"];
const vendorDirectories = ["vendor/docx", "vendor/pdf", "vendor/pptx", "vendor/xlsx", "vendor/libarchive"];

async function copyFile(relativePath) {
  const target = path.join(outputRoot, relativePath);
  await mkdir(path.dirname(target), { recursive: true });
  await cp(path.join(sourceRoot, relativePath), target);
}

async function copyDirectory(relativePath) {
  await cp(path.join(sourceRoot, relativePath), path.join(outputRoot, relativePath), {
    recursive: true,
    force: true,
  });
}

await rm(outputRoot, { recursive: true, force: true });
await mkdir(outputRoot, { recursive: true });
await copyFile("flyfish-file-viewer-web-full.iife.js");
await copyFile("flyfish-viewer-assets.json");
await copyFile("flyfish-viewer-manifest.json");
for (const renderer of rendererNames) await copyFile(`renderers/${renderer}.iife.js`);
for (const vendor of vendorDirectories) await copyDirectory(vendor);

const attribution = await readFile(new URL("./THIRD_PARTY.md", import.meta.url), "utf8");
await writeFile(path.join(outputRoot, "THIRD_PARTY.md"), attribution, "utf8");

const manifest = {
  package: "@file-viewer/web-full",
  version: "2.1.29",
  renderers: rendererNames,
  vendors: vendorDirectories,
};
await writeFile(path.join(outputRoot, "nomi-asset-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");

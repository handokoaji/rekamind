// Regenerasi ikon aplikasi dari docs/assets/logo.svg. Jalankan dari web/: CHROMIUM_PATH=... node ../scripts/make_icons.mjs (lalu gabungkan icon.ico dengan ImageMagick).
import { chromium } from "playwright";
import fs from "fs";
const svg = fs.readFileSync("../docs/assets/logo.svg","utf8");
const b = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
const p = await b.newPage();
async function png(size, out, inner) {
  await p.setViewportSize({width:size,height:size});
  await p.setContent(`<body style="margin:0;background:transparent">${inner ?? svg.replace("<svg",`<svg width="${size}" height="${size}"`)}</body>`);
  await p.screenshot({path: out, omitBackground: true});
}
const d="../desktop/src-tauri/icons/";
for (const [s,n] of [[512,"icon.png"],[32,"32x32.png"],[128,"128x128.png"],[256,"128x128@2x.png"],[256,"_ico256.png"],[48,"_ico48.png"],[16,"_ico16.png"]]) await png(s,d+n);
// tray: idle = logo, recording = logo with red dot
const rec = svg.replace("</svg>",'<circle cx="25" cy="25" r="6" fill="#dc2626" stroke="#fff" stroke-width="1.5"/></svg>').replace("<svg",'<svg width="32" height="32"');
await png(32,d+"tray-idle.png");
await png(32,d+"tray-recording.png",rec);
await b.close();

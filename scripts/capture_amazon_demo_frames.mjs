// Capture generated cards plus live /ui/ and /firetv/ frames for the 15-beat remux.
// Requires local API (CARE_LADDER_ALLOW_INSECURE_LOCAL=1) and puppeteer-core.
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import puppeteer from "puppeteer-core";

const ROOT = process.env.ROOT || process.cwd();
const BASE = process.env.BASE || "http://127.0.0.1:8010";
const OUT = process.env.FRAMES || path.join(ROOT, "docs/demo/frames");
const CHROME =
  process.env.CHROME ||
  (fs.existsSync("/opt/google/chrome/chrome")
    ? "/opt/google/chrome/chrome"
    : "/usr/local/bin/chrome");

fs.mkdirSync(OUT, { recursive: true });

function loadStory() {
  const p = path.join(OUT, "story.json");
  if (!fs.existsSync(p)) throw new Error(`missing ${p}; run amazon_demo_story.py first`);
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

async function shot(page, name) {
  const dest = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: dest, type: "png" });
  console.log("wrote", dest);
}

async function sanitizeFireTv(page) {
  await page.evaluate(() => {
    const hide = (sel) =>
      document.querySelectorAll(sel).forEach((el) => {
        el.style.display = "none";
      });
    hide("#console");
    hide("#consoleToggle");
    hide("#agentTools");
    hide("#gateBackdrop");
    hide("#cShowTools");
    hide(".audit");
    hide("#auditEvents");
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        node.nodeValue = node.nodeValue
          .replaceAll("\u2014", ", ")
          .replaceAll("\u2013", "-")
          .replaceAll(" — ", ", ")
          .replace(/\backed\b/gi, "acknowledged")
          .replace(/\bfall\b/gi, "cue");
      } else if (node.childNodes) {
        node.childNodes.forEach(walk);
      }
    };
    walk(document.body);
  });
}

async function sanitizeUi(page) {
  await page.evaluate(() => {
    document.querySelectorAll(".inc-id, .trace-link, .fall-banner, [data-ack]").forEach((el) => {
      el.style.display = "none";
    });
    document.querySelectorAll(".clipsec, .dossier img").forEach((el) => {
      el.style.display = "none";
    });
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        node.nodeValue = node.nodeValue
          .replaceAll("\u2014", ", ")
          .replaceAll("\u2013", "-")
          .replace(/\backed\b/gi, "acknowledged")
          .replace(/\bfall signature\b/gi, "cue")
          .replace(/\bFall signature\b/g, "Cue");
      } else if (node.childNodes) {
        node.childNodes.forEach(walk);
      }
    };
    walk(document.body);
    document.querySelectorAll(".tl-head").forEach((btn) => {
      if (btn.getAttribute("aria-expanded") !== "true") btn.click();
    });
  });
}

async function main() {
  const story = loadStory();
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: [
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--hide-scrollbars",
      "--allow-file-access-from-files",
      "--window-size=1280,720",
    ],
    defaultViewport: { width: 1280, height: 720, deviceScaleFactor: 1 },
  });
  const page = await browser.newPage();
  page.setDefaultTimeout(20000);

  const overlay = pathToFileURL(path.join(ROOT, "scripts/demo_overlays.html")).href;
  await page.goto(overlay, { waitUntil: "networkidle0" });
  await page.evaluate((s) => {
    window.fillStory(s);
  }, story);

  const scenes = [
    ["map", "b01_map"],
    ["phone_dead", "b02_battery"],
    ["phone_call", "b02_call"],
    ["title", "b03_title"],
    ["ladder_setup", "b04_ladder"],
    ["cue_log", "b05_cue"],
    ["alexa_notify", "b06_notify"],
    ["apl_card", "b06_apl"],
    ["defer_sister", "b07_defer"],
    ["split", "b08_split"],
    ["mum_silent", "b09_silent"],
    ["neighbor_notify", "b10_neighbor"],
    ["neighbor_going", "b11_going"],
    ["shes_okay", "b11_okay"],
    ["how_is_mum", "b11_status"],
    ["routine", "b12_routine"],
    ["roster_msg", "b12_roster"],
    ["architecture", "b14_arch"],
    ["pytest", "b14_pytest"],
    ["close", "b15_close"],
  ];
  for (const [id, name] of scenes) {
    await page.evaluate((sid) => window.showScene(sid), id);
    await new Promise((r) => setTimeout(r, 120));
    await shot(page, name);
  }

  // Live Fire TV ambient view (supporting surface). Sanitize copy first.
  await page.goto(`${BASE}/firetv/`, { waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 900));
  await sanitizeFireTv(page);
  await new Promise((r) => setTimeout(r, 200));
  await shot(page, "b13_firetv");

  // Live console: event log only, IDs and live frames hidden.
  await page.goto(`${BASE}/ui/`, { waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 700));
  await sanitizeUi(page);
  await new Promise((r) => setTimeout(r, 200));
  await shot(page, "b05_ui");

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

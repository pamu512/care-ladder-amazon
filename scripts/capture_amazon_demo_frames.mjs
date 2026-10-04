// Capture live /ui/ and /firetv/ frames for the Amazon remux.
// Requires local API (CARE_LADDER_ALLOW_INSECURE_LOCAL=1) and puppeteer-core.
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import puppeteer from "puppeteer-core";

const ROOT = process.env.ROOT || process.cwd();
const BASE = process.env.BASE || "http://127.0.0.1:8010";
const OUT = process.env.FRAMES || path.join(ROOT, "docs/demo/frames");
const CHROME = process.env.CHROME || "/opt/google/chrome/chrome";
const PY = process.env.PY || path.join(ROOT, ".venv/bin/python");

fs.mkdirSync(OUT, { recursive: true });

async function postFixture(fixture) {
  const res = await fetch(`${BASE}/demo/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fixture }),
  });
  if (!res.ok) {
    throw new Error(`demo/run ${fixture} -> ${res.status} ${await res.text()}`);
  }
  return res.json();
}

async function latestIncident() {
  const list = await (await fetch(`${BASE}/incidents`)).json();
  const mine = list.filter((i) => i.household_id === "amazon-demo-1");
  if (!mine.length) return null;
  const id = mine[mine.length - 1].id;
  return (await fetch(`${BASE}/incidents/${id}`)).json();
}

async function ackLatest() {
  const inc = await latestIncident();
  if (!inc) throw new Error("no incident to ack");
  const res = await fetch(`${BASE}/incidents/${inc.id}/ack`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contact: "caregiver", note: "demo remux ack" }),
  });
  if (!res.ok) throw new Error(`ack ${res.status} ${await res.text()}`);
}

async function shot(page, name) {
  const dest = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: dest, type: "png" });
  console.log("wrote", dest);
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: [
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--hide-scrollbars",
      "--window-size=1280,720",
    ],
    defaultViewport: { width: 1280, height: 720, deviceScaleFactor: 1 },
  });
  const page = await browser.newPage();
  page.setDefaultTimeout(20000);

  await postFixture("no_movement_silence");
  await page.goto(`${BASE}/ui/`, { waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 800));
  await shot(page, "shot01_ui");

  await page.goto(`${BASE}/firetv/`, { waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 900));
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowRight");
  await shot(page, "shot03_allclear");

  const soft = await postFixture("alexa_path_a_soft_ok");
  await page.reload({ waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 1200));
  await page.click("#consoleToggle");
  await new Promise((r) => setTimeout(r, 400));
  await shot(page, "shot04_soft_ok");
  fs.writeFileSync(path.join(OUT, "shot04_incident.json"), JSON.stringify(soft));

  await page.click("#consoleToggle");
  const human = await postFixture("alexa_path_a_needs_human");
  await page.reload({ waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 1200));
  await shot(page, "shot05_needs_human");
  fs.writeFileSync(path.join(OUT, "shot05_incident.json"), JSON.stringify(human));

  await ackLatest();
  await page.reload({ waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 1000));
  await shot(page, "shot06_acked");

  await postFixture("alexa_path_b");
  await page.reload({ waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 1200));
  await shot(page, "shot07_occluded");

  const sim = spawnSync(
    PY,
    ["-m", "care_ladder.mcp_server.alexa_sim", "--url", BASE, "--answer", "don't worry"],
    { encoding: "utf8", env: { ...process.env, CARE_LADDER_ALLOW_INSECURE_LOCAL: "1" } },
  );
  const log = (sim.stdout || "") + (sim.stderr || "");
  fs.writeFileSync(path.join(OUT, "shot08_sim.log"), log);
  await page.reload({ waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 1200));
  await page.evaluate(() => {
    const btn = document.getElementById("cShowTools");
    if (btn) btn.click();
  });
  await new Promise((r) => setTimeout(r, 400));
  await shot(page, "shot08_firetv");

  await page.goto(`${BASE}/firetv/`, { waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 800));
  await page.evaluate(() => {
    document.getElementById("gateBackdrop")?.classList.add("open");
  });
  await new Promise((r) => setTimeout(r, 300));
  await shot(page, "shot09_gate");

  await page.goto(`${BASE}/ui/`, { waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 600));
  await shot(page, "shot10_ui");
  await page.goto(`${BASE}/firetv/`, { waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 800));
  await shot(page, "shot10_firetv");

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

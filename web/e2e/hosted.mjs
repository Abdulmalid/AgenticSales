// Smoke test against a console wired to a REAL hosted API (no seeded data needed):
//   BASE=http://localhost:3000 ADMIN_KEY=ask_... OUT=./out node e2e/hosted.mjs
import { chromium } from "playwright-core";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const KEY = process.env.ADMIN_KEY;
const OUT = process.env.OUT ?? "./e2e-out";
const CHROME = process.env.CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
fs.mkdirSync(OUT, { recursive: true });

const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  -> " + detail : ""}`); };

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const failedUrls = [];
page.on("response", (r) => { if (r.status() >= 400 && !r.url().includes("favicon")) failedUrls.push(`${r.status()} ${r.url()}`); });
page.on("console", (m) => { if (m.type() === "error" && !m.text().includes("favicon") && !m.text().includes("Failed to load resource")) errors.push(m.text()); });

await page.goto(`${BASE}/login`);
await page.fill('input[name="key"]', KEY);
await page.click('button[type="submit"]');
await page.waitForURL(`${BASE}/`, { timeout: 30000 });
await page.waitForSelector("h1");
check("signs in against the hosted API", (await page.textContent("h1")).includes("Welcome back"), (await page.textContent("h1")).trim());
await page.screenshot({ path: `${OUT}/h1-dashboard.png`, fullPage: true });

await page.goto(`${BASE}/playground`);
await page.fill('textarea[aria-label="Customer message"]', "Oga, how much be the iPhone 15?");
await page.keyboard.press("Enter");
await page.waitForSelector(".msg.agent:not(.typing)", { timeout: 150000 });
const reply = (await page.locator(".msg.agent").last().textContent()) ?? "";
check("playground gets a real reply from the hosted agent", reply.length > 5 && reply.includes("800,000"), reply.slice(0, 90).replace(/\s+/g, " "));
await page.screenshot({ path: `${OUT}/h2-playground.png`, fullPage: true });
await page.getByRole("button", { name: "Why?" }).last().click();
await page.waitForSelector("dialog[open] ol li", { timeout: 20000 });
check("'Why?' pulls the audit trail from the hosted API", (await page.locator("dialog[open]").textContent()).includes("Understood the message"));

await page.goto(`${BASE}/leads`);
await page.waitForSelector("h1");
check("the new lead appears under Leads", (await page.locator("tbody tr").count()) >= 1);
await page.screenshot({ path: `${OUT}/h3-leads.png`, fullPage: true });

for (const [path, expect] of [["/approvals", "Decisions your AI agent"], ["/analytics", "What's working"], ["/content", "Content studio"], ["/settings", "Teach the agent"], ["/settings?tab=channels", "write-only"]]) {
  const r = await page.goto(BASE + path);
  await page.waitForSelector("h1");
  const t = (await page.textContent("main")) ?? "";
  check(`${path} renders from hosted data`, r.status() === 200 && t.includes(expect) && !t.includes("Couldn't load"));
}
check("no browser console errors", errors.length === 0, errors.slice(0, 2).join(" | "));
check("no failed network requests", failedUrls.length === 0, failedUrls.slice(0, 3).join(" | "));
await browser.close();
const bad = results.filter((x) => !x).length;
console.log(`\n${results.length - bad}/${results.length} checks passed`);
process.exit(bad ? 1 : 0);

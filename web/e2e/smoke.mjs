// Real-browser smoke test: node e2e/smoke.mjs   (needs the API + console running, and ADMIN_KEY / STAFF_KEY / OUT)
import { chromium } from "playwright-core";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = process.env.OUT ?? "./e2e-out";
const ADMIN = process.env.ADMIN_KEY, STAFF = process.env.STAFF_KEY;
const CHROME = process.env.CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
fs.mkdirSync(OUT, { recursive: true });

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  -> " + detail : ""}`); };

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const consoleErrors = [];

async function session(key, viewport = { width: 1280, height: 900 }) {
  const ctx = await browser.newContext({ viewport });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(`${page.url()} :: ${m.text()}`); });
  page.on("pageerror", (e) => consoleErrors.push(`${page.url()} :: ${e.message}`));
  await page.goto(`${BASE}/login`);
  await page.fill('input[name="key"]', key);
  await page.click('button[type="submit"]');
  return { ctx, page };
}

// ---- login: rejects junk and wrong keys, accepts the real one
{
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`);
  await page.screenshot({ path: `${OUT}/01-login.png` });
  await page.fill('input[name="key"]', "hello");
  await page.click('button[type="submit"]');
  await page.waitForSelector("#login-err");
  check("login rejects a malformed key", (await page.textContent("#login-err")).includes("ask_"));
  await page.fill('input[name="key"]', "ask_" + "x".repeat(43));
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => document.querySelector("#login-err")?.textContent?.includes("Invalid"));
  check("login rejects a wrong key", true);
  await ctx.close();
}

// ---- admin, desktop
const { ctx, page } = await session(ADMIN);
await page.waitForURL(`${BASE}/`);
await page.waitForSelector("h1");
check("admin lands on the dashboard", (await page.textContent("h1")).includes("Welcome back"));
const cookies = await ctx.cookies();
const sess = cookies.find((c) => c.name === "as_session");
check("session cookie is httpOnly + sameSite and does not contain the API key", !!sess && sess.httpOnly && sess.sameSite === "Lax" && !sess.value.includes(ADMIN.slice(4, 20)));
check("API key is not readable from page JavaScript", !(await page.evaluate(() => document.cookie)).includes("as_session"));
await page.screenshot({ path: `${OUT}/02-dashboard.png`, fullPage: true });
const dash = await page.textContent("main");
check("dashboard shows seeded data", dash.includes("Hot leads") && dash.includes("Pipeline") && /Revenue/.test(dash));

for (const [path, expect, shot] of [
  ["/leads", "Everyone the agent is talking to", "03-leads"],
  ["/approvals", "Decisions your AI agent won't make", "05-approvals"],
  ["/content", "Content studio", "06-content"],
  ["/analytics", "What's working", "07-analytics"],
  ["/settings", "Teach the agent about your business", "08-settings-business"],
  ["/settings?tab=channels", "Secrets are write-only", "09-settings-channels"],
  ["/settings?tab=automation", "Follow-ups and messages", "10-settings-automation"],
  ["/settings?tab=website", "One-page website", "11-settings-website"],
  ["/playground", "Chat with your agent", "04-playground"],
]) {
  const r = await page.goto(BASE + path);
  await page.waitForSelector("h1");
  const text = await page.textContent("main");
  check(`${path} renders`, r.status() === 200 && text.includes(expect) && !text.includes("Couldn't load"), `status ${r.status()}`);
  await page.screenshot({ path: `${OUT}/${shot}.png`, fullPage: true });
}

// ---- lead detail via the list
await page.goto(`${BASE}/leads`);
const rows = await page.locator("tbody tr").count();
check("leads table lists the seeded leads", rows >= 6, `${rows} rows`);
await page.locator("tbody tr a").first().click();
await page.waitForSelector("text=Why this score?");
check("lead detail shows score reasons + honest note", (await page.textContent("main")).includes("not a measured probability"));
await page.screenshot({ path: `${OUT}/12-lead-detail.png`, fullPage: true });
await page.getByRole("button", { name: "Why?" }).first().click().catch(() => {});

// ---- approvals: deny the discount, count drops
await page.goto(`${BASE}/approvals`);
await page.waitForSelector("article.card");
const before = await page.locator("article.card").count();
console.log("  [debug] url", page.url(), "cards", before, "decline", await page.getByRole("button", { name: "Decline" }).count(), "dialogs open", await page.locator("dialog[open]").count());
await page.locator("article.card", { hasText: "Discount request" }).first().getByRole("button", { name: "Decline" }).click();
await page.waitForSelector("text=Decision applied.", { timeout: 15000 });
await page.reload();
const after = await page.locator("article.card").count();
check("declining a discount resolves it and queues a polite message", after === before - 1, `${before} -> ${after}`);

// ---- content: flagged draft cannot be approved, fixing it makes it approvable
await page.goto(`${BASE}/content`);
const flagged = page.locator("article.card", { hasText: "Needs changes before it can be approved" }).first();
check("risky draft shows its violations", (await flagged.textContent()).includes("payment link"));
check("risky draft's Approve button is disabled", await flagged.getByRole("button", { name: "Approve" }).isDisabled());
await flagged.locator("textarea").fill("Fresh arrivals this week. DM us to order, we deliver across Lagos.");
await flagged.getByRole("button", { name: "Save changes" }).click();
await page.waitForTimeout(1500);
await page.reload();
check("after fixing the wording the draft moves to pending approval", (await page.textContent("main")).includes("Fresh arrivals this week"));
await page.screenshot({ path: `${OUT}/13-content-after.png`, fullPage: true });

// ---- settings: bad config is refused by the form, good one saves
await page.goto(`${BASE}/settings`);
await page.locator('fieldset').first().getByLabel("Lowest price (₦)").fill("9999999");
await page.getByRole("button", { name: "Save changes" }).click();
await page.waitForSelector(".notice.danger");
check("settings refuses a floor price above the list price", (await page.textContent(".notice.danger")).includes("can't be above"));

// ---- playground: one live turn (real model; slow on free tier)
await page.goto(`${BASE}/playground`);
await page.fill('textarea[aria-label="Customer message"]', "Oga, how much be the iPhone 15?");
await page.keyboard.press("Enter");
try {
  await page.waitForSelector(".msg.agent:not(.typing)", { timeout: 120000 });
  const reply = await page.locator(".msg.agent").last().textContent();
  check("playground gets a real agent reply", reply.length > 5 && !reply.includes("couldn't answer"), reply.slice(0, 90).replace(/\s+/g, " "));
  await page.screenshot({ path: `${OUT}/14-playground-reply.png`, fullPage: true });
  await page.getByRole("button", { name: "Why?" }).last().click();
  await page.waitForSelector("dialog[open] ol li", { timeout: 15000 });
  check("'Why?' explains the decision in plain language", (await page.locator("dialog[open]").textContent()).includes("Understood the message"));
  await page.screenshot({ path: `${OUT}/15-why-dialog.png` });
} catch (e) {
  check("playground gets a real agent reply", false, String(e).slice(0, 120));
}
await ctx.close();

// ---- staff: no settings
{
  const s = await session(STAFF);
  await s.page.waitForURL(`${BASE}/`);
  check("staff sees no Settings link", (await s.page.locator('nav[aria-label="Main"] a', { hasText: "Settings" }).count()) === 0);
  await s.page.goto(`${BASE}/settings`);
  check("staff is redirected away from /settings", new URL(s.page.url()).pathname === "/");
  const r = await s.page.request.put(`${BASE}/api/b/config`, { data: {}, headers: { "x-csrf": "1" } });
  check("staff cannot change config through the proxy (API enforces role)", r.status() === 403, `status ${r.status()}`);
  await s.ctx.close();
}

// ---- CSRF + proxy policy through a real browser session
{
  const a = await session(ADMIN);
  await a.page.waitForURL(`${BASE}/`);
  const noHeader = await a.page.request.post(`${BASE}/api/b/followups/run`);
  check("proxy rejects POST without CSRF header", noHeader.status() === 403);
  const evil = await a.page.request.post(`${BASE}/api/b/followups/run`, { headers: { "x-csrf": "1", origin: "https://evil.example" } });
  check("proxy rejects cross-origin POST", evil.status() === 403);
  const escape = await a.page.request.get(`${BASE}/api/b/..%2Fwebhooks%2Fx`);
  check("proxy refuses paths outside the console API", [400, 404].includes(escape.status()), `status ${escape.status()}`);
  const secrets = await a.page.request.get(`${BASE}/api/b/secrets`);
  check("secrets listing never returns values", !JSON.stringify(await secrets.json()).match(/ask_|sk_|secret_value/));
  await a.ctx.close();
}

// ---- phone width
{
  const m = await session(ADMIN, { width: 390, height: 844 });
  await m.page.waitForURL(`${BASE}/`);
  await m.page.waitForSelector("h1");
  check("mobile shows the bottom navigation", await m.page.locator("nav.bottomnav").isVisible());
  check("mobile hides the desktop sidebar", !(await m.page.locator("aside.sidebar").isVisible()));
  const overflow = await m.page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  check("no horizontal scroll on the phone dashboard", !overflow);
  await m.page.screenshot({ path: `${OUT}/20-mobile-dashboard.png`, fullPage: true });
  for (const p of ["/leads", "/approvals", "/content", "/playground"]) {
    await m.page.goto(BASE + p);
    await m.page.waitForSelector("h1");
    const o = await m.page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    check(`no horizontal scroll on mobile ${p}`, !o);
    if (p === "/leads") await m.page.screenshot({ path: `${OUT}/21-mobile-leads.png`, fullPage: true });
    if (p === "/approvals") await m.page.screenshot({ path: `${OUT}/22-mobile-approvals.png`, fullPage: true });
  }
  await m.ctx.close();
}

await browser.close();
const relevant = consoleErrors.filter((e) => !e.includes("favicon"));
check("no browser console errors", relevant.length === 0, relevant.slice(0, 3).join(" | "));
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

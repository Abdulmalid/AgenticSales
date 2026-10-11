import { test } from "node:test";
import assert from "node:assert/strict";
import { deriveKey, seal, unseal, type Session } from "../lib/seal.ts";
import { checkProxyRequest, passthroughType } from "../lib/policy.ts";
import { naira, relTime, titleCase, toKobo, who } from "../lib/format.ts";

test("titleCase turns API enums into readable labels", () => {
  assert.equal(titleCase("READY_TO_BUY"), "Ready To Buy");
  assert.equal(titleCase("lead_generation"), "Lead Generation");
  assert.equal(titleCase("fraud_review"), "Fraud Review");
});

const key = deriveKey("x".repeat(40), true);
const sess: Session = { key: "ask_secret", tenant: "demo", role: "admin", business: "PhoneHub", exp: Date.now() + 60_000 };

test("session round-trips and the API key never appears in the cookie", () => {
  const token = seal(sess, key);
  assert.ok(!token.includes("ask_secret") && !Buffer.from(token, "base64url").toString("latin1").includes("ask_secret"));
  assert.deepEqual(unseal(token, key), sess);
});

test("tampered, truncated, expired and wrong-key sessions are rejected", () => {
  const token = seal(sess, key);
  const flipped = token.slice(0, -2) + (token.endsWith("AA") ? "BB" : "AA");
  assert.equal(unseal(flipped, key), null);
  assert.equal(unseal(token.slice(0, 20), key), null);
  assert.equal(unseal(token, deriveKey("y".repeat(40), true)), null);
  assert.equal(unseal(seal({ ...sess, exp: Date.now() - 1 }, key), key), null);
  assert.equal(unseal(undefined, key), null);
  assert.equal(unseal(seal({ ...sess, role: "root" as never }, key), key), null);
});

test("production refuses a missing or short secret; development has a fallback", () => {
  assert.throws(() => deriveKey(undefined, true));
  assert.throws(() => deriveKey("short", true));
  assert.ok(deriveKey(undefined, false).length === 32);
});

const base = { method: "GET", segments: ["leads"], origin: null, selfOrigin: "https://app.example", csrfHeader: null, contentLength: null };

test("proxy only reaches allow-listed API areas with clean paths", () => {
  assert.deepEqual(checkProxyRequest(base), { ok: true, backendPath: "/v1/leads" });
  assert.equal(checkProxyRequest({ ...base, segments: ["leads", "12"] }).ok, true);
  for (const bad of [["webhooks", "x"], ["..", "etc"], ["leads", ".."], ["lea ds"], ["leads", "a/b"], [], ["a", "b", "c", "d", "e"]]) {
    assert.equal(checkProxyRequest({ ...base, segments: bad }).ok, false, JSON.stringify(bad));
  }
  assert.equal(checkProxyRequest({ ...base, method: "PATCH" }).ok, false);
});

test("mutating requests need the csrf header and a same-origin Origin", () => {
  const post = { ...base, method: "POST", segments: ["chat"] };
  assert.equal(checkProxyRequest(post).ok, false);                                   // no header
  assert.equal(checkProxyRequest({ ...post, csrfHeader: "1" }).ok, true);            // same-site fetch (no Origin)
  assert.equal(checkProxyRequest({ ...post, csrfHeader: "1", origin: "https://evil.example" }).ok, false);
  assert.equal(checkProxyRequest({ ...post, csrfHeader: "1", origin: "https://app.example" }).ok, true);
  assert.equal(checkProxyRequest({ ...post, csrfHeader: "1", contentLength: 10_000_000 }).ok, false);
});

test("only json and images pass through", () => {
  assert.equal(passthroughType("application/json; charset=utf-8"), "json");
  assert.equal(passthroughType("image/png"), "image");
  assert.equal(passthroughType("text/html"), "other");
  assert.equal(passthroughType("image/svg+xml"), "other");   // SVG can carry script
  assert.equal(passthroughType(null), "other");
});

test("money and time formatting", () => {
  assert.equal(naira(80_000_000), "₦800,000");
  assert.equal(naira(80_000_000, { compact: true }), "₦800k");
  assert.equal(naira(250_000_000_00, { compact: true }), "₦250M");
  assert.equal(naira(null), "–");
  assert.equal(toKobo("₦1,250.50"), 125050);
  assert.throws(() => toKobo("abc"));
  assert.equal(relTime(new Date(Date.now() - 3 * 3600_000).toISOString()), "3h ago");
  assert.equal(relTime(null), "–");
  assert.equal(who("whatsapp:2348012345678"), "2348•••678");
  assert.equal(who("whatsapp:2348012345678", "Ada"), "Ada");
});

/** @input Mock browser fetch. @output Request and CSRF contract tests. @position Frontend verification. @doc-sync Update INDEX.md on changes. */
import { afterEach, expect, it, vi } from "vitest";
import { api, setCsrf } from "./api";
afterEach(() => vi.unstubAllGlobals());
it("sends session credentials and CSRF on writes", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(new Response('{"ok":true}', { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  setCsrf("test-csrf");
  expect(await api("/runs", "POST", { task: "x" })).toEqual({ ok: true });
  const [url, options] = fetch.mock.calls[0];
  expect(url).toBe("/api/v1/runs");
  expect(options.credentials).toBe("include");
  expect(options.headers["X-CSRF-Token"]).toBe("test-csrf");
  expect(options.body).toBe('{"task":"x"}');
});
it("propagates API error detail", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(new Response('{"detail":"denied"}', { status: 403 })),
  );
  await expect(api("/runs")).rejects.toThrow("denied");
});
it("does not override multipart boundaries", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", fetch);
  const form = new FormData();
  form.append("file", new Blob(["x"]), "x.txt");
  await api("/uploads/attachment", "POST", form);
  expect(fetch.mock.calls[0][1].headers["Content-Type"]).toBeUndefined();
});

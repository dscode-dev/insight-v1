import { describe, expect, it } from "vitest";

import { classifyReminderWrite } from "@/lib/control-plane/reminders-routing";

/**
 * This classification is the only thing separating an audited mute from
 * an unaudited one — and an unaudited mute still succeeds, so nothing
 * surfaces the omission.
 *
 * Why muting is the governed act: it does not move the deadline, it
 * changes who finds out. The reminders seeded today cover the mTLS pair
 * between Gateway and Social and the Cloudflare token rotations, so a
 * silenced reminder is a credential expiring with nobody watching. The
 * audit record is the only evidence that someone chose that.
 */
describe("classifyReminderWrite", () => {
  it("governs a mute and extracts the slug", () => {
    expect(classifyReminderWrite("mtls-social-cert/mute")).toEqual({
      kind: "governed",
      slug: "mtls-social-cert",
    });
  });

  it.each([
    ["", "the collection — creating a policy"],
    ["cloudflare-service-token/done", "recording a rotation"],
    ["mtls-social-cert/observed", "reporting an observed expiry"],
  ])("treats %p as ordinary (%s)", (path) => {
    // These leave their evidence in the row itself: the new period, the
    // new last_done_at, the new observed_at. Nothing is hidden by them.
    expect(classifyReminderWrite(path)).toEqual({ kind: "ordinary" });
  });

  /**
   * Fails closed. Every one of these ENDS in /mute, so it would reach the
   * mute endpoint upstream — demoting any of them to the ordinary branch
   * would forward the write with no audit at all.
   */
  it.each([
    ["a/b/mute", "extra segment"],
    ["/mute", "empty slug"],
    ["Mtls-Social/mute", "uppercase — not a slug this service issues"],
    ["a%2Fb/mute", "encoded separator, decodes into a path"],
    ["%E0%A4%A/mute", "malformed percent-escape"],
  ])("refuses %p (%s)", (path) => {
    expect(classifyReminderWrite(path)).toEqual({
      kind: "refuse",
      reason: "malformed_mute_path",
    });
  });

  it("does not govern a path that merely contains the word mute", () => {
    expect(classifyReminderWrite("mute-something/done")).toEqual({
      kind: "ordinary",
    });
  });
});

import { describe, it, expect } from "vitest";
import { sanitizeRichHtml } from "./sanitize";

describe("sanitizeRichHtml", () => {
  it("removes script tags", () => {
    const dirty = '<p>Hello</p><script>alert("x")</script>';
    const clean = sanitizeRichHtml(dirty);
    expect(clean).toContain("<p>Hello</p>");
    expect(clean).not.toContain("<script>");
    expect(clean).not.toContain("alert(");
  });

  it("blocks javascript protocol links", () => {
    const dirty = '<a href="javascript:alert(1)">click</a>';
    const clean = sanitizeRichHtml(dirty);
    expect(clean).toContain("<a");
    expect(clean).not.toContain("javascript:");
  });
});

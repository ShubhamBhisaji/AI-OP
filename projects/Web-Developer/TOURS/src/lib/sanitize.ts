import sanitizeHtml from "sanitize-html";

const ALLOWED_TAGS = [
  "p",
  "br",
  "strong",
  "em",
  "u",
  "s",
  "blockquote",
  "code",
  "pre",
  "ul",
  "ol",
  "li",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "a",
  "img",
];

const ALLOWED_ATTRIBUTES: Record<string, string[]> = {
  a: ["href", "name", "target", "rel"],
  img: ["src", "alt", "title", "width", "height"],
};

const ALLOWED_SCHEMES = ["http", "https", "mailto", "tel"];

export function sanitizeRichHtml(input: string): string {
  return sanitizeHtml(input || "", {
    allowedTags: ALLOWED_TAGS,
    allowedAttributes: ALLOWED_ATTRIBUTES,
    allowedSchemes: ALLOWED_SCHEMES,
    disallowedTagsMode: "discard",
    transformTags: {
      a: sanitizeHtml.simpleTransform("a", {
        rel: "noopener noreferrer nofollow",
        target: "_blank",
      }),
    },
  });
}

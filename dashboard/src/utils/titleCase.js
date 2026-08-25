// Chicago-style title casing, shared across the app (Landing Page headlines, Service names, ...).
// Extracted verbatim from the Landing Page Builder so both surfaces format identically.

export const HEADLINE_MINOR_WORDS = new Set([
  "a", "an", "the",
  "and", "but", "or", "nor", "for", "yet", "so",
  "as", "at", "by", "in", "of", "off", "on", "per", "to", "up", "via",
  "if", "vs", "vs.",
]);

export function formatHeadline(text) {
  if (!text || typeof text !== "string") return text || "";
  const parts = text.split(/(\s+)/);
  const wordIndexes = parts.map((part, index) => (part && !/\s+/.test(part) ? index : -1)).filter((index) => index >= 0);
  if (!wordIndexes.length) return text;
  const firstWord = wordIndexes[0];
  const lastWord = wordIndexes[wordIndexes.length - 1];
  return parts.map((part, index) => {
    if (!part || /\s+/.test(part)) return part;
    return formatHeadlineWord(part, index === firstWord, index === lastWord);
  }).join("");
}

function formatHeadlineWord(word, isFirst, isLast) {
  if (word.length >= 2 && word === word.toUpperCase() && /^[A-Z]+$/.test(word)) return word;
  const leading = word.match(/^[^a-zA-Z]*/)?.[0] || "";
  const trailing = word.match(/[^a-zA-Z]*$/)?.[0] || "";
  const endIndex = trailing ? word.length - trailing.length : word.length;
  const core = word.slice(leading.length, endIndex);
  if (!core) return word;
  if (core.length >= 2 && core === core.toUpperCase() && /^[A-Z]+$/.test(core)) return word;
  const lowerCore = core.toLowerCase();
  if (lowerCore === "s" && /[\d']$/.test(leading)) return `${leading}${core}${trailing}`;
  if (!isFirst && !isLast && HEADLINE_MINOR_WORDS.has(lowerCore)) return `${leading}${lowerCore}${trailing}`;
  return `${leading}${capitalizeHeadlineCore(lowerCore)}${trailing}`;
}

function capitalizeHeadlineCore(word) {
  if (!word) return word;
  if (word.includes("-")) return word.split("-").map(capitalizeHeadlineCore).join("-");
  return word.charAt(0).toUpperCase() + word.slice(1);
}

// Live <input> handler: title-case as the user types while preserving the caret position.
// `assign` receives the formatted value (e.g. (value) => { form.name = value; }).
export function applyTitleCaseInput(assign, event) {
  const input = event.target;
  const original = input.value;
  const formatted = formatHeadline(original);
  const cursorFromEnd = original.length - input.selectionStart;
  assign(formatted);
  if (formatted !== original) {
    input.value = formatted;
    const nextPosition = Math.max(0, formatted.length - cursorFromEnd);
    requestAnimationFrame(() => input.setSelectionRange(nextPosition, nextPosition));
  }
}

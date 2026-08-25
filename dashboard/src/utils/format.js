// Shared display formatters for list/detail dashboard screens.

// Epoch seconds -> localized date/time. Accepts numbers or numeric strings
// (order records store created_at as a string), returns an em dash for empties.
export function formatEpochDate(value, { withTime = true } = {}) {
  const seconds = Number(value);
  if (!seconds || Number.isNaN(seconds)) return "—";
  const options = withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" };
  return new Intl.DateTimeFormat("en-US", options).format(new Date(seconds * 1000));
}

// snake_case / lowercase status -> "Title Case" label.
export function statusLabel(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .trim() || "—";
}

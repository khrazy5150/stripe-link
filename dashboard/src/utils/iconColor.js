// Deterministic pastel background + matching foreground derived from an id/name, so that
// same-icon placeholders (e.g. every service's tools icon) read as visually distinct.
export function idColorStyle(key) {
  const str = String(key || "");
  let hash = 0;
  for (let i = 0; i < str.length; i += 1) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return {
    backgroundColor: `hsl(${hue}, 65%, 88%)`,
    color: `hsl(${hue}, 55%, 28%)`,
  };
}

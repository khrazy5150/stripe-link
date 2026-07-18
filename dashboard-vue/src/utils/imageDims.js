// Intrinsic image dimensions captured at upload time so the renderer can reserve layout space
// (no CLS) and hint crawlers. The processor already reports the source dimensions in its status
// response; we key them by the rendition base — every rendition/format of one asset shares that
// base and the same aspect ratio. Mirror of the Python rendition_base()/collect_image_dims().

const RENDITION_RE = /^(.+)\/(?:thumb|small|medium|large|full)\.(?:webp|jpe?g|png)$/i;

// .../<key>/<size>.<ext> -> .../<key>; a non-rendition (external/custom) URL keys by its full self.
export function renditionBase(url) {
  const match = RENDITION_RE.exec(String(url || ""));
  return match ? match[1] : String(url || "");
}

// Best available [width, height] for an uploaded asset: the processor's authoritative source
// dimensions when present, else the dimensions of whichever rendition the browser probed.
export function dimsFromStatus(body, probe) {
  const source = body && body.source;
  if (source && Number(source.width) > 0 && Number(source.height) > 0) {
    return [Number(source.width), Number(source.height)];
  }
  if (probe && Number(probe.width) > 0 && Number(probe.height) > 0) {
    return [Number(probe.width), Number(probe.height)];
  }
  return null;
}

// Record dims for a URL into a base-keyed map (mutates and returns it). No-op without dims.
export function recordImageDims(map, url, dims) {
  if (url && Array.isArray(dims) && dims[0] > 0 && dims[1] > 0) {
    map[renditionBase(url)] = [dims[0], dims[1]];
  }
  return map;
}

// The subset of a dims map whose keys back the given URLs — so a saved document carries only the
// dimensions of images it actually references, not stale entries from removed uploads.
export function imageDimsForUrls(map, urls) {
  const out = {};
  const source = map || {};
  for (const url of urls || []) {
    const base = renditionBase(url);
    if (source[base]) out[base] = source[base];
  }
  return out;
}

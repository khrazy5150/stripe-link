import { apiRequest, toAssetCdnUrl } from "./client";
import { dimsFromStatus } from "../utils/imageDims";

// Shared tenant image-upload flow: presign a POST to the media bucket, upload the file,
// then poll the processing pipeline until a rendition URL is servable. Used by the landing
// page builder and the services catalog. basePrefix groups the object (e.g. "offers",
// "services") within the target bucket. Resolves to { url, dims: [w, h] | null } — dims are the
// processor's source dimensions so callers can record them for CLS-free rendering.
export async function uploadImage(file, { basePrefix = "offers", targetBucket = "images.juniorbay.net" } = {}) {
  if (!file.type.startsWith("image/") || file.size > 10 * 1024 * 1024) throw new Error("Use an image file up to 10MB.");
  const presigned = await apiRequest("/upload/multiple", {
    method: "POST",
    body: {
      fileName: file.name,
      contentType: file.type,
      basePrefix,
      targetBucket,
    },
  });
  const formData = new FormData();
  Object.entries(presigned.upload?.fields || {}).forEach(([key, value]) => formData.append(key, value));
  formData.append("file", file);
  const uploadResponse = await fetch(presigned.upload.url, { method: "POST", body: formData });
  if (!uploadResponse.ok) throw new Error("Failed to upload file.");
  return pollImageUrl(presigned.id);
}

async function pollImageUrl(imageId) {
  const deadline = Date.now() + 180000;
  let delay = 1200;
  while (Date.now() < deadline) {
    await sleep(delay);
    delay = Math.min(8000, Math.ceil(delay * 1.35));
    const body = await apiRequest(`/upload/status/${encodeURIComponent(imageId)}`).catch(() => ({}));
    if (body.status === "failed") throw new Error("Image processing failed.");
    for (const url of imageUrlCandidates(body.urls || {})) {
      const probe = await imageUrlLoads(url);
      if (probe.ok) return { url, dims: dimsFromStatus(body, probe) };
    }
  }
  throw new Error("Timed out waiting for processed image.");
}

function imageUrlCandidates(urls) {
  return [...new Set([
    urls.small?.webp,
    urls.small?.jpg,
    urls.medium?.webp,
    urls.medium?.jpg,
    urls.large?.webp,
    urls.large?.jpg,
    urls.original,
  ].filter(Boolean).map(cdnImageUrl))];
}

function cdnImageUrl(url) {
  return toAssetCdnUrl(url);  // upload bucket host -> configured asset CDN (public_asset_base_url)
}

function imageUrlLoads(url, timeoutMs = 4000) {
  return new Promise((resolve) => {
    const image = new Image();
    const timeout = window.setTimeout(() => finish(false), timeoutMs);
    function finish(ok) {
      window.clearTimeout(timeout);
      const dims = ok ? { width: image.naturalWidth, height: image.naturalHeight } : {};
      image.onload = null;
      image.onerror = null;
      resolve({ ok, ...dims });
    }
    image.onload = () => finish(true);
    image.onerror = () => finish(false);
    image.src = `${url}${url.includes("?") ? "&" : "?"}_probe=${Date.now()}`;
  });
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}


// Tenant video upload. Same presign-POST-then-poll flow as uploadImage, with mediaType "video" so the
// processor routes it to the videos/ prefix and copies the original through untouched. There is NO
// transcode (see docs/EXTERNAL_SERVICES.md), so the file we accept is the file visitors download —
// hence mp4/webm only and a size cap well under the service's 100MB ceiling: a hero video is the
// largest thing on a landing page, and page speed is the whole point of these pages.
const VIDEO_UPLOAD_TYPES = ["video/mp4", "video/webm"];
const MAX_VIDEO_BYTES = 50 * 1024 * 1024;

export async function uploadVideo(file, { basePrefix = "offers", targetBucket = "images.juniorbay.net" } = {}) {
  if (!VIDEO_UPLOAD_TYPES.includes(file.type)) {
    throw new Error("Use an MP4 or WebM video. Other formats aren't converted, so they may not play for every visitor.");
  }
  if (file.size > MAX_VIDEO_BYTES) {
    throw new Error("Use a video up to 50MB — larger hero videos slow the page down badly on mobile.");
  }
  const presigned = await apiRequest("/upload/multiple", {
    method: "POST",
    body: {
      fileName: file.name,
      contentType: file.type,
      basePrefix,
      targetBucket,
      mediaType: "video",
    },
  });
  const formData = new FormData();
  Object.entries(presigned.upload?.fields || {}).forEach(([key, value]) => formData.append(key, value));
  formData.append("file", file);
  const uploadResponse = await fetch(presigned.upload.url, { method: "POST", body: formData });
  if (!uploadResponse.ok) throw new Error("Failed to upload the video.");
  return pollVideoUrl(presigned.id);
}

// Videos cannot be probed with an Image(), and there are no renditions to wait for — the processor
// writes urls.original once the copy completes, so that is the ready signal.
async function pollVideoUrl(uploadId) {
  const deadline = Date.now() + 300000;  // a 50MB copy takes longer than an image resize
  let delay = 1500;
  while (Date.now() < deadline) {
    await sleep(delay);
    delay = Math.min(8000, Math.ceil(delay * 1.35));
    const body = await apiRequest(`/upload/status/${encodeURIComponent(uploadId)}`).catch(() => ({}));
    if (body.status === "failed" || body.status === "error") throw new Error("Video processing failed.");
    const original = body.urls?.original;
    if (original) return toAssetCdnUrl(original);
  }
  throw new Error("Timed out waiting for the uploaded video.");
}

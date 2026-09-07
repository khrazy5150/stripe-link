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
      if (probe.ok) return { url, dims: dimsFromStatus(body, probe), imageId };
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
// transcode (see docs/EXTERNAL_SERVICES.md), so the file we accept is the file visitors download.
//
// The SIZE LIMIT IS NOT DEFINED HERE. The service returns `maxBytes` for this upload and bakes the same
// number into the presigned POST's content-length-range, so S3 enforces it. Raising the ceiling (course
// video, say) is a stack parameter on image-processing — no code change here, no dashboard release.
// We presign first and check second: presigning is one fast call, uploading the bytes is the slow part,
// so this still fails fast without a client-side copy of the limit.
const VIDEO_UPLOAD_TYPES = ["video/mp4", "video/webm"];

export async function uploadVideo(file, { basePrefix = "offers", targetBucket = "images.juniorbay.net" } = {}) {
  if (!VIDEO_UPLOAD_TYPES.includes(file.type)) {
    throw new Error("Use an MP4 or WebM video. Other formats aren't converted, so they may not play for every visitor.");
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
  const maxBytes = Number(presigned.maxBytes) || 0;
  if (maxBytes && file.size > maxBytes) {
    throw new Error(`This video is ${formatMb(file.size)}. The limit is ${formatMb(maxBytes)}.`);
  }
  const formData = new FormData();
  Object.entries(presigned.upload?.fields || {}).forEach(([key, value]) => formData.append(key, value));
  formData.append("file", file);
  const uploadResponse = await fetch(presigned.upload.url, { method: "POST", body: formData });
  // S3 rejects an oversize body itself via content-length-range, so this covers a stale presign too.
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

function formatMb(bytes) {
  return `${Math.round((Number(bytes) || 0) / (1024 * 1024))}MB`;
}


/**
 * Bake a crop into a new derivative and return its URL.
 *
 * For ASSET images -- product, service, landing hero -- the crop cannot live in CSS: the same photo also
 * feeds `og:image` and Product JSON-LD, which are URLs in meta tags that no stylesheet can reach. A
 * CSS-cropped product would still send the uncropped image to Facebook and Google.
 *
 * Always cropped from the ORIGINAL (the service reads the source by id), so re-cropping never compounds
 * a previous crop.
 */
export async function cropImage(imageId, crop, { width = 1600, height = 1600 } = {}) {
  if (!imageId) throw new Error("This image was added before cropping existed, so it cannot be cropped.");
  const body = await apiRequest("/upload/crop", {
    method: "POST",
    body: {
      image_id: imageId,
      width: Math.round(width),
      height: Math.round(height),
      crop: { x: crop.x, y: crop.y, w: crop.w, h: crop.h },
    },
  });
  const url = imageUrlCandidates(body.urls || {})[0];
  if (!url) throw new Error("The cropped image could not be generated.");
  return url;
}

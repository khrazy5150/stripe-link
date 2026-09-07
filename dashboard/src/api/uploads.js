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
  // Same reasoning as pollVideoUrl: an image resize is FASTER than a video copy, so an opening delay of
  // 1200ms was overshooting even further past the moment the work was done.
  let delay = 400;
  while (Date.now() < deadline) {
    await sleep(delay);
    delay = Math.min(3000, Math.ceil(delay * 1.3));
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

export async function uploadVideo(file, { basePrefix = "offers", targetBucket = "images.juniorbay.net", onProgress = null } = {}) {
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
  // S3 rejects an oversize body itself via content-length-range, so a failure here covers a stale presign.
  await postWithProgress(presigned.upload.url, formData, onProgress);
  // The bytes have landed; what remains is the processor, which cannot report a percentage. Saying so is
  // more honest than leaving "Uploading" on screen while nothing is uploading.
  if (onProgress) onProgress({ phase: "processing", percent: 100 });
  return pollVideoUrl(presigned.id);
}

// Videos cannot be probed with an Image(), and there are no renditions to wait for — the processor
// writes urls.original once the copy completes, so that is the ready signal.
/**
 * POST to S3 with real progress.
 *
 * fetch() cannot report upload progress, so the whole transfer was opaque -- the button read "Uploading..."
 * from the first byte until processing finished, covering two phases of very different length with one
 * word. A 500MB ceiling makes that potentially minutes of silence, which is what makes an upload feel
 * broken rather than slow.
 */
function postWithProgress(url, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress({ phase: "uploading", percent: Math.round((event.loaded / event.total) * 100) });
      }
    });
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300
      ? resolve()
      : reject(new Error("Failed to upload the video.")));
    xhr.onerror = () => reject(new Error("Failed to upload the video."));
    xhr.send(formData);
  });
}

async function pollVideoUrl(uploadId) {
  const deadline = Date.now() + 300000;  // a 50MB copy takes longer than an image resize
  // Measured 2026-09-07: the processor finishes a video in ~2s using 119MB of its 1024MB, and the queue
  // adds no delay -- so the wait a tenant felt was almost entirely THIS schedule. Starting at 1500ms with
  // a 1.35x backoff put the checks at 1.5s, 3.5s, 6.3s, 9.9s: a job done at 2s was not noticed until 3.5s,
  // and one done at 7s waited until 9.9s. Polling opens tighter and backs off gently instead. Each check
  // costs ~0.45s round trip, so this is a handful of extra cheap requests, not a busy loop.
  let delay = 500;
  while (Date.now() < deadline) {
    await sleep(delay);
    delay = Math.min(3000, Math.ceil(delay * 1.3));
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

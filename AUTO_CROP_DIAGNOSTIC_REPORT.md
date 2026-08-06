# LockletPro Auto Crop — Deep Diagnostic Report

## Instrumentation Added (DO NOT REMOVE UNTIL ROOT CAUSE FIXED)

### 1. ScanDocumentScreen.kt
- **AUTO_CROP ENTRY**: Logs bitmap size, orientation, aspect ratio, config (pixel format).
- **Preview state**: Logs `detectedQuad` presence and `imageWidth` / `imageHeight`.
- **Quad source**: Logs whether preview quad is used (with scale and corner coords) or detection is called.
- **FALLBACK_TRIGGER**: When detection returns null, logs `"FALLBACK_TRIGGER: detection returned no quad"`.

**Lines**: ~206–230 (ProcessMode.AUTO_CROP block).

---

### 2. AutoCropProcessor.kt
- **Bitmap before detection**: Size and orientation.
- **Preview quad path**: Validated vs out-of-bounds; logs `FALLBACK_TRIGGER: QUAD_OUT_OF_BOUNDS` when invalid.
- **Preview quad NULL**: Logs when running detection fallback with bitmap size.
- **Quad detected**: Logs corner coords and that PerspectiveTransformer will run.
- **Warp executed**: Logs result mat size after transform.
- **Warp skipped**: Logs `FALLBACK_TRIGGER: NO_QUAD` or `NOT_QUAD(size=N)` when warp is skipped.
- **EXCEPTION**: Logs `FALLBACK_TRIGGER: EXCEPTION` with message and stack.

**Lines**: ~222–265 (detectAndCrop), ~291–293 (catch).

---

### 3. DocumentEdgeDetector.kt
- **Downscale**: Scale factor and original vs result size (when scale &lt; 1).
- **Contour analysis** (per pass): `contours.size`, `frameArea`, `maxArea`, `areaRatio`, `minAreaRequired`.
- **NO_CONTOURS**: When `contours.isEmpty()` — `FILTER_FAILURE: NO_CONTOURS`.
- **SMALL_AREA**: When largest contour area &lt; minArea — `FILTER_FAILURE: SMALL_AREA` (for first contour).
- **ASPECT_RATIO**: When aspect outside [MIN_ASPECT, MAX_ASPECT] — `FILTER_FAILURE: ASPECT_RATIO`.
- **POLYGON NOT QUAD**: When `approxPolyDP` returns size != 4 — logs size and corner coords.
- **NOT_CONVEX**: When 4 points but not convex — `FILTER_FAILURE: NOT_CONVEX`.
- **NO_VALID_QUAD**: When contours exist but all rejected — `FILTER_FAILURE: NO_VALID_QUAD`.
- **Per-pass result**: Logs which pass (Canny50_150, Canny30_100, Otsu, Sobel) returned null or a quad.
- **ALL_PASSES_NULL**: When all four passes return null — `FALLBACK_TRIGGER: ALL_PASSES_NULL`.
- **EXCEPTION**: Logs `FALLBACK_TRIGGER: EXCEPTION` with message.
- **Debug overlay**: `lastDebugContourPoints`, `lastDebugImageWidth`, `lastDebugImageHeight` set when first contour is processed but does not yield a valid quad (for red overlay).

**Lines**: ~44–60 (downscale), ~62–118 (detectLargestQuad + fallback reasons), ~106–198 (detectQuadFromMat with contour analysis and filter failure logs).

---

### 4. PerspectiveTransformer.kt
- **WARP_SKIPPED**: When `points.size != 4` — logs reason and corner coords.
- **warpPerspective CALLED**: Src/dst dimensions and TL/TR/BR/BL.
- **warpPerspective DONE**: Result mat size.

**Lines**: ~16–20, ~38–42.

---

### 5. Debug Overlay (ScanDocumentScreen + DocumentOverlay)
- **DocumentOverlay**: Optional `debugContourPoints`, `debugContourImageW`, `debugContourImageH`. When `debug` is true and these are set, draws the detected-but-rejected contour in **red** (4f stroke) on the preview.
- **ScanDocumentScreen**: Passes `DocumentEdgeDetector.lastDebugContourPoints` and dimensions into `DocumentOverlay` so the last “imperfect” contour is visible when detection fails.

**Lines**: DocumentOverlay ~845–900; ScanDocumentScreen ~758–767.

---

## How to Use the Diagnostic

1. Run the app, open scanner, point at a document, and tap **Auto Crop** (or capture then Auto Crop).
2. Filter Logcat by tags: `ScanDocumentScreen`, `LockletProEnhancer`, `DocumentEdgeDetector`, `PerspectiveTransformer`.
3. Search for `[DIAG]` and `FALLBACK_TRIGGER` to see the path and exact failure point.
4. If in **camera preview** the green quad appears but **after capture** it falls back, compare:
   - `[DIAG] Preview state: detectedQuad=... imageWidth=... imageHeight=...`
   - `[DIAG] AUTO_CROP ENTRY: bitmapSize=...` (captured bitmap may have different size/orientation).
5. If you see a **red contour** on preview, detection found a contour but it was rejected (not 4 points, not convex, or area/aspect filter). Logs will show which of POLYGON NOT QUAD / NOT_CONVEX / SMALL_AREA / ASPECT_RATIO / NO_VALID_QUAD occurred.

---

## Root Cause Categories (Use Logs to Pick One)

| Category | What to look for in logs | Files / area |
|----------|---------------------------|--------------|
| **Detection failure** | `NO_CONTOURS`, `SMALL_AREA`, `areaRatio` very low, or all passes null | DocumentEdgeDetector (contour analysis, pass results) |
| **Filtering too strict** | `FILTER_FAILURE: SMALL_AREA` or `ASPECT_RATIO` or `NOT_CONVEX` with plausible numbers | DocumentEdgeDetector (minArea, MIN_ASPECT, MAX_ASPECT, convex check) |
| **Sorting error** | Quad found but warp produces wrong crop (wrong order of corners) | PerspectiveTransformer (TL/TR/BR/BL order), getOrderedPointsRobust |
| **Warp error** | `warpPerspective CALLED` then crash or bad result | PerspectiveTransformer, AutoCropProcessor (transform call) |
| **Bitmap input issue** | `bitmapSize` or `orientation` or `config` unexpected; rotation mismatch | ScanDocumentScreen (decode), ImageCapture vs analyzer rotation |
| **Scaling issue** | Preview quad valid but `QUAD_OUT_OF_BOUNDS`; or downscale size destroys edges | ScanDocumentScreen (scaleX/scaleY), DocumentEdgeDetector (MAX_DIMENSION_DETECTION, downscale log) |

---

## Fallback Trigger Reference

- **NO_CONTOURS** — DocumentEdgeDetector found no contours.
- **SMALL_AREA** — Largest contour below 10% of frame.
- **ASPECT_RATIO** — Contour bounding box aspect outside [0.2, 5.0].
- **POLYGON NOT QUAD** — approxPolyDP did not return 4 points.
- **NOT_CONVEX** — 4 points but not convex.
- **NO_VALID_QUAD** — Contours exist but every one rejected by above.
- **ALL_PASSES_NULL** — Canny (x2), Otsu, Sobel all returned null.
- **QUAD_OUT_OF_BOUNDS** — Preview quad failed bounds check in AutoCropProcessor.
- **NO_QUAD** — AutoCropProcessor got null from detector.
- **NOT_QUAD(size=N)** — Quad had points.size != 4.
- **WARP_FAILURE** — PerspectiveTransformer skipped (points.size != 4) or warp error.
- **EXCEPTION** — Any exception in pipeline (detector or processor).

Use this report together with `[DIAG]` and `FALLBACK_TRIGGER` log lines to identify the **exact** reason Auto Crop always falls back, then fix only that cause.

---

## STEP 8 — ROOT CAUSE REPORT (after running app and checking logs)

### ROOT CAUSE CATEGORY (pick the one that matches your Logcat)

Use the first `[DIAG]` or `FALLBACK_TRIGGER` that appears in the pipeline to choose:

| # | Category | Log to look for | File | Lines |
|---|----------|------------------|------|-------|
| 1 | **Scaling issue** | `Preview state: detectedQuad=false` or `imageWidth=0 imageHeight=0` → preview quad never used; or `QUAD_OUT_OF_BOUNDS` | ScanDocumentScreen.kt | 210–219; AutoCropProcessor.kt 227–236 |
| 2 | **Bitmap input issue** | `bitmapSize` very different from preview; `rotationDegrees` non-zero and not applied to quad; wrong aspect | ScanDocumentScreen.kt | 207, 324–332 (decode + EXIF log) |
| 3 | **Detection failure** | `NO_CONTOURS` or `contours.size=0`; `areaRatio` &lt; 0.1; `ALL_PASSES_NULL` | DocumentEdgeDetector.kt | 172–176, 111 |
| 4 | **Filtering too strict** | `FILTER_FAILURE: SMALL_AREA` or `ASPECT_RATIO` or `POLYGON NOT QUAD` or `NOT_CONVEX` or `NO_VALID_QUAD` | DocumentEdgeDetector.kt | 184–230 (detectQuadFromMat) |
| 5 | **Sorting error** | Quad detected, warp called, but crop looks wrong (wrong corners) | DocumentEdgeDetector.kt 303–307 (getOrderedPointsRobust); PerspectiveTransformer.kt 16–20 |
| 6 | **Warp error** | `WARP_SKIPPED` or exception inside PerspectiveTransformer | PerspectiveTransformer.kt | 16–20, 43–47; AutoCropProcessor.kt 247–249 |
| 7 | **EXCEPTION** | `FALLBACK_TRIGGER: EXCEPTION` | DocumentEdgeDetector.kt 114; AutoCropProcessor.kt 298 |

### Most likely chain (if you see “always fallback”)

1. **Preview quad not used**: `detectedQuad=null` or `imageWidth=0`/`imageHeight=0` at capture time → **Scaling / state issue** (ScanDocumentScreen.kt 209–211, 221–226).  
2. **Detection on capture bitmap fails**: `Calling DocumentEdgeDetector.detectLargestQuad` then `Detection returned null` and in DocumentEdgeDetector `FILTER_FAILURE` or `ALL_PASSES_NULL` → **Detection failure** or **Filtering too strict** (DocumentEdgeDetector.kt 172–230).  
3. **Preview quad passed but rejected**: `Using preview quad` then `QUAD_OUT_OF_BOUNDS` → **Scaling issue** (AutoCropProcessor.kt 227–236): scale from preview to capture puts corners outside bitmap.

### Files and lines responsible (quick reference)

- **ScanDocumentScreen.kt**: 207–226 (AUTO_CROP entry, preview state, detection call), 324–332 (rotation/EXIF).
- **AutoCropProcessor.kt**: 219–256 (quad choice, warp vs fallback), 298 (EXCEPTION).
- **DocumentEdgeDetector.kt**: 56–60 (downscale), 75–111 (passes + ALL_PASSES_NULL), 127–230 (detectQuadFromMat: contours, filter failures).
- **PerspectiveTransformer.kt**: 16–20 (WARP_SKIPPED), 43–47 (warpPerspective called/done).

**Algorithm was not modified; only diagnostics were added.**

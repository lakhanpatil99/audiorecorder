# Locklet Pro Scanner Forensic Audit Report

## 1. Scanner Architecture
**Current Processing Flow:**
1. **Capture:** Image is captured and downscaled if either dimension exceeds 2048px (to avoid OOM). It normalizes orientation.
2. **Process:** Depending on `ProcessMode` (`AUTO_CROP`, `ENHANCE`, `OCR`, `ORIGINAL`), it routes to `AutoCropProcessor`.
3. **Auto Crop:** Calls `DocumentEdgeDetector.detectLargestQuad`. Uses Canny Edge Detection & Otsu Thresholding. If 4 points are found, applies perspective warp (`PerspectiveTransformer`). Fallbacks to `smartCenterCropAndEnhance` (crops center 88%).
4. **Enhance:** Uses OpenCV (Primary) or Android Canvas Matrix (Fallback). Modes include ULTRA_HD, NATURAL, VIBRANT_POP, BLACK_WHITE.
5. **OCR:** Runs `OCRProcessor` inline during the enhance step.
6. **Save:** Bitmaps are compressed to JPEG (quality 97) in cache, and Uris are returned to the UI.

---

## 2. Auto Crop Findings
**Root Causes for Auto Crop Failures:**
*   **Strict Quad Requirement:** `detectQuadFromMat` requires exactly 4 points (`approxArray.size == 4`). If a document has a rounded corner, a slight tear, or a finger overlapping an edge, the polygon approximation will return 5+ points, causing the detection to instantly fail.
*   **Removed minAreaRect Fallback:** Code comments indicate `minAreaRect fallback` was removed. This means non-perfect quads instantly fail instead of gracefully degrading to a bounding box.
*   **Canny Threshold Aggressiveness:** The `Canny(20, 80)` pass was removed, leaving less sensitive thresholds. Low-contrast documents (e.g., white paper on a light gray desk) fail to produce distinct edges.
*   **Fallback Behavior:** When detection fails, `smartCenterCropAndEnhance` simply crops 12% off the edges (center 88%). This does not actually detect the document, leaving messy backgrounds intact.

---

## 3. Enhancement Findings
**Root Causes for Image Degradation:**
*   **Washouts & Lost Detail (e.g., PAN Cards):** In `ULTRA_HD` and `NATURAL` modes, the app uses a global contrast modifier that aggressively blows out highlights. The Android Canvas fallback uses `ColorMatrix` with fixed flat additions (`+10` or `+5` to RGB channels). In the OpenCV path, CLAHE (Contrast Limited Adaptive Histogram Equalization) uses a very high clip limit of `3.5`, which forces bright areas (like PAN card backgrounds) to turn completely white, destroying text and watermarks.
*   **Unnatural Colors (Pink/Orange Backgrounds):** `VIBRANT_POP` forcibly boosts saturation by `1.25x` in the HSV color space, and `ULTRA_HD` uses `Core.addWeighted` to mix the image with itself. This amplifies existing color casts in shadows or low-light photos, turning subtle warm tones into harsh pinks/oranges.

---

## 4. Ultra HD Findings
**Pipeline Audit:**
*   **Is it enhancing?** No, it is artificially inflating values.
*   **Upscaling:** Yes. It unconditionally upscales the final matrix by 15% (`Imgproc.resize(..., 1.15, 1.15, INTER_CUBIC)`).
*   **Brightness & Contrast:** It increases both via LAB space CLAHE and a Gamma correction curve (`1.15`).
*   **Sharpening:** Yes, it applies a basic 3x3 high-pass filter matrix `(0 -1 0, -1 6 -1, 0 -1 0)`.
**Why it looks worse than professional scanners:**
Upscaling a noisy image by 15%, then hitting it with global gamma, heavy CLAHE, and a rigid sharpening matrix amplifies sensor noise. Professional apps use edge-preserving unsharp masking and document binarization (whitening the background while keeping text black), rather than blindly saturating and sharpening the whole image.

---

## 5. Save Crash Findings
**Root Causes for Crash (Auto Crop → Save):**
*   **Bitmap Recycling Race Condition:** In `ScanDocumentScreen.kt`, within the `AUTO_CROP` processing block, the result bitmap is recycled immediately after being written to the cache file:
    `if (resultBitmap != bitmap) { resultBitmap.recycle() }` and `bitmap.recycle()`.
    If the UI or Coil attempts to access the memory reference before the file URI is fully propagated or if it shares a reference, a `Recycled Bitmap` crash occurs.
*   **Perspective Warp OOM:** In `PerspectiveTransformer.kt`, the dimensions of the output bitmap (`maxWidth`, `maxHeight`) are calculated based on the Euclidean distance between detected points. If edge detection returns anomalous points (e.g., intersecting lines or bowtie shapes due to poor sorting), `maxWidth` and `maxHeight` can jump to massive values (e.g., 10,000+ pixels). `Bitmap.createBitmap` will instantly throw an `OutOfMemoryError`.

---

## 6. Performance Findings
**Root Causes for Bottlenecks:**
*   **Heavy CPU Blocking:** `Photo.fastNlMeansDenoisingColored` is used in the OpenCV pipeline. This algorithm is notoriously slow and designed for high-end photography, not mobile document scanning. It causes significant frame drops.
*   **Memory Leaks / OOM Risks:** In `AutoCropProcessor.kt`, multiple large `Mat` objects (`originalMat`, `grayMat`, `blurredMat`, `enhancedMat`, `upscaledMat`) are kept in memory simultaneously. A 2048px image takes ~16MB per Mat.
*   **Coroutine Usage:** While processing is offloaded to `Dispatchers.Default`, there is no concurrency limit. Rapidly clicking filters or captures can spawn multiple concurrent 100MB+ memory operations, leading to OOM.

---

## 7. Missing Professional Features
Compared to Adobe Scan, Microsoft Lens, and CamScanner, this module is missing:
*   **Document Whitening / Binarization:** No algorithm removes the background color to pure white while preserving color in photos/logos (Adaptive Local Binarization).
*   **Shadow Removal:** No illumination estimation to flatten uneven lighting or shadows caused by the user's phone.
*   **Edge-Preserving Sharpening:** Uses a basic high-pass filter instead of an Unsharp Mask, causing halos around text.
*   **Perspective Deskew Interpolation:** Missing advanced interpolation during warp, leading to jagged text.
*   **Robust Corner Detection:** Lacks Hough Transform line intersections for corner finding.

---

## 8. Risk Assessment
*   **Save Crashes (OOM / Recycled Bitmap):** **HIGH**
*   **Auto Crop Failures (Strict 4-point rule):** **HIGH**
*   **Image Degradation (Washouts / Color clipping):** **HIGH**
*   **Performance (fastNlMeans blocking):** **MEDIUM**
*   **OCR Safety:** **LOW** (OCR pipeline is isolated and functional).

---

## 9. Target Files
Files requiring modification to fix the identified issues:
*   `ScanDocumentScreen.kt` (Bitmap lifecycle, coroutine scope)
*   `AutoCropProcessor.kt` (Enhancement algorithms, NLP denoising removal, memory cleanup)
*   `DocumentEdgeDetector.kt` (Contour filtering, Hough lines implementation)
*   `PerspectiveTransformer.kt` (Dimension capping, quad validation)

---

## 10. Recommended Fix Strategy
*   **Auto Crop:** Replace contour approximation with Hough Line Transform to find the 4 strongest intersecting lines, generating a quad even if the physical document edge is interrupted.
*   **Enhancement:** Remove `fastNlMeansDenoisingColored`. Replace global CLAHE with a localized adaptive threshold (e.g., Sauvola binarization) mapped back to color to whiten backgrounds without clipping foregrounds.
*   **Ultra HD:** Remove the `1.15x` upscaling. Apply an Unsharp Mask instead of a fixed 3x3 kernel.
*   **Stability:** Implement a maximum dimension cap inside `PerspectiveTransformer.warp`. Defer bitmap recycling to the UI layer via `DisposableEffect` rather than inside the processing functions.
*   **Colors:** Implement a white-balance estimator (Grey World assumption) before applying saturation, to prevent the pink/orange tinting.

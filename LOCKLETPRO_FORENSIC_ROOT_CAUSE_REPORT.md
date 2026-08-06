# LOCKLET-PRO SCANNER — FORENSIC ROOT CAUSE ANALYSIS REPORT (POST-STABILIZATION)

**Role:** Senior Computer Vision Engineer + Android Performance Architect + OpenCV Specialist  
**Project:** LockletPro Android App — Document Scanner Module  
**Objective:** Full forensic diagnostic — root causes only (no fixes, no code changes)  
**Scope:** Current codebase after orientation, convexity, warp pipeline, and threading fixes  
**Benchmark:** Production-level behavior (Adobe Scan, Microsoft Lens, CamScanner, Google Drive Scanner)  
**Date:** 2025

---

## 1. FEATURE STABILITY TABLE

| System | Stability | Primary Failure Mode | Severity |
|--------|-----------|----------------------|----------|
| **Manual Crop (drag)** | Improved | Convex fallback can replace user quad; mapper identity edge case | Medium |
| **Manual Crop (confirm)** | Improved | Warp at 2048; long Default block still possible; silent enhance/OCR failure | Medium |
| **Auto Crop detection** | Improved | Orientation normalized; relaxed thresholds; TL/TR/BR/BL order; residual threshold/lighting failure | Medium |
| **Auto Crop (preview→capture)** | Improved | EXIF applied; scale now consistent when orientation matches | Low |
| **PerspectiveTransformer** | Stable | Degenerate quad validation; Mat release correct | Low |
| **CoordinateMapper** | Stable | convexClampQuad; display rect clamp during drag | Low |
| **CropOverlayComposable** | Improved | Drag clamped to displayRect; convexClampQuad on end | Low |
| **ScanDocumentScreen pipeline** | Improved | Orientation applied; file I/O on IO; preview quad used when available | Low |
| **DocumentEdgeDetector** | Improved | getOrderedPointsRobust (y then x); multi-pass Canny; relaxed area; Otsu/Sobel return unordered then ordered in caller | Medium |
| **AutoCropProcessor** | Improved | applyLockletProEnhancement try/finally Mat release | Low |
| **OCRProcessor** | Stable | try/catch returns null; no crash | Low |
| **BitmapExtensions** | Stable | normalizeBitmapOrientation; downscale; SCANNER_MAX_DIMENSION | Low |
| **Navigation / result passing** | Stable | savedStateHandle; ManualCrop → ScanDocument | Low |
| **Compose (overlay + zoom/pan)** | Partial | Recomposition on every drag; mapper recreated on zoom | Medium |

---

## 2. CRITICAL ROOT CAUSES (RESIDUAL)

### 2.1 Convex fallback replaces entire quad

**Observation:** `CoordinateMapper.convexClampQuad` first clamps per-point, then checks `clamped.isValid(minSidePx)`. If invalid (non-convex, duplicate, or too small), it **returns a fully new inset rectangle** and discards the user’s quad. The user can perceive “my crop jumped to a rectangle” when they had a nearly crossing or degenerate quad.

**Root cause:** No attempt to fix the quad in place (e.g. by moving only the offending corner). Fallback is all-or-nothing.

### 2.2 normalizeBitmapOrientation on Default

**Observation:** In `ScanDocumentScreen` (LaunchedEffect) and `ManualCropScreen` (LaunchedEffect), `normalizeBitmapOrientation(context, bitmap, uri)` is invoked from a coroutine on `Dispatchers.Default`. The function uses `context.contentResolver.openInputStream(uri)` and reads EXIF — i.e. file I/O.

**Root cause:** Blocking I/O runs on the Default dispatcher. It can delay other Default work and, under load, contribute to perceived latency. Not a strict main-thread ANR.

### 2.3 Silent failure in ManualCrop confirm

**Observation:** In ManualCropScreen confirm, `AutoCropProcessor.detectAndCrop` and `OCRProcessor.extractText` are wrapped in `try { ... } catch (e: Exception) { null }`. On failure, the pipeline continues with unenhanced bitmap or no OCR text; the user is not informed.

**Root cause:** Exceptions are swallowed; no user-visible error or fallback message.

### 2.4 Preview quad scale assumes dimensions match

**Observation:** When using the preview quad, scale is `scaleX = bitmap.width / imageWidth`, `scaleY = bitmap.height / imageHeight`. This is correct when the capture bitmap has the same orientation as the preview (after EXIF normalization) and when dimensions match. If decode uses `inSampleSize` and the preview analyzer used a different resolution, dimensions can differ; scaling is then by aspect, which is correct only if both are the same orientation.

**Root cause:** No explicit check that `imageWidth`/`imageHeight` refer to the same orientation as the decoded bitmap; reliance on EXIF normalization and consistent pipeline. If a code path ever skipped normalization or used different sampling, scale would be wrong.

### 2.5 Otsu/Sobel return unordered points

**Observation:** In `detectQuadOtsuPass` and `detectQuadSobelPass`, when `approxArray.size == 4`, the code returns `approxArray.toList()` with no ordering. In `detectLargestQuad`, the result is always passed to `getOrderedPointsRobust`, so the final DocumentQuad is ordered TL,TR,BR,BL. The minAreaRect fallback in Otsu/Sobel explicitly calls `getOrderedPointsRobust`.

**Root cause:** Direct return of `approxArray.toList()` is internally consistent because the caller orders it. Residual risk: any future use of Otsu/Sobel return value without ordering would break warp order.

### 2.6 Mapper identity during drag

**Observation:** `mapper2` is created with `remember(displayRect2.left, displayRect2.top, displayRect2.width, displayRect2.height, bitmapSize)`. On zoom/pan, `displayRect2` changes and a new mapper is created. `CropOverlayComposable` uses `pointerInput(Unit)`, so the gesture block is stable, but it closes over `mapper` from composition. If recomposition runs after zoom and before the user’s drag end, the mapper passed to `containerToBitmap` and `convexClampQuad` could be the new one; if there is any ordering where the overlay reads an outdated mapper, coordinates could be wrong.

**Root cause:** Mapper is not stable across zoom; dependency on composition order and timing for correct mapper at drag end.

---

## 3. MATHEMATICAL ERRORS

| Location | Error | Impact |
|----------|--------|--------|
| **convexClampQuad fallback** | Fallback is full inset rect; no attempt to preserve three corners and adjust one | User quad can be fully replaced → surprising crop |
| **CropQuad.isConvex** | Cross product sign 0 is ignored (no branch); all-zero cross can pass | Degenerate (collinear) quad could be considered convex if all cross products are zero |
| **PerspectiveTransformer.isValidQuad** | Collinearity check uses `abs(cross) < 1e-10`; convexity uses strict sign; duplicate uses DUPLICATE_EPS 4.0 | Tight collinearity threshold may reject valid quads on rounding; duplicate threshold is in pixel units and may be large for small images |

No remaining errors in container↔bitmap formulas, display rect clamp during drag, or TL/TR/BR/BL ordering in detection.

---

## 4. PIPELINE BREAKPOINTS

```
[Camera] → ImageCapture → save to file → URI
    ↓
[ScanDocumentScreen] LaunchedEffect(capturedImageUri)
    ↓ Decode (maxDim 2048) on Default
    ↓ normalizeBitmapOrientation (IO on Default)
    ↓ processDocument(oriented, ...)
    │  ├─ AUTO_CROP: preview quad scaled by bitmap.width/imageWidth (orientation now consistent)
    │  ├─ File I/O in withContext(Dispatchers.IO) ✓
    │  └─ Warp/enhance on Default; quad from detection or preview
    ↓ Main: displayedImageUri, toast
    ↓
[ManualCrop] decode with inSampleSize (max 2048), normalize orientation, detect or fullBounds
    ↓ Drag: clamp to mapper.displayRect; onDragEnd convexClampQuad
    ↓ Confirm: convexClampQuad → warp(bitmap≤2048) → enhance → OCR → IO save
    ↓ savedStateHandle → popBackStack
[ScanDocumentScreen] getLiveData(manual_crop_result_uri).observeAsState() → consume
```

**Residual breakpoints:** normalizeBitmapOrientation does IO on Default. Convex fallback replaces quad. Silent enhance/OCR failure in ManualCrop.

---

## 5. PERFORMANCE BOTTLENECKS

| Step | Bottleneck | Location |
|------|------------|----------|
| Manual crop confirm | Single long Default block (warp + enhance + OCR) | ManualCropScreen scope.launch → withContext(Default) |
| normalizeBitmapOrientation | openInputStream + ExifInterface read on Default | BitmapExtensions + ScanDocumentScreen / ManualCropScreen |
| Overlay during drag | Recomposition on every containerPoints update | CropOverlayComposable reads containerPoints → overlay + 4 handles |
| Mapper | Recreated when displayRect2 or bitmapSize changes | remember(displayRect2.*, bitmapSize) |
| Detection | Multiple Canny/Otsu/Sobel passes on 1600px copy | DocumentEdgeDetector.detectLargestQuad |

Warp no longer runs on full 12MP; decode uses sampling in ManualCropScreen. File I/O is on IO.

---

## 6. MEMORY RISKS

| Risk | Source | Notes |
|------|--------|------|
| **Bitmap in state** | ManualCropScreen holds bitmap (max 2048 after sampling) | Lower than before; still non-trivial on low-end devices |
| **applyLockletProEnhancement** | try/finally releases dest and intermediates on throw | Residual: B&W branch returns inside try without going through finally for temp/lab/channels (they are null there); color branch releases in finally. Safe. |
| **Recycle on orientation** | ScanDocumentScreen / ManualCropScreen recycle when oriented != bitmap | Correct. |
| **ManualCrop resultBitmap** | enhanced?.bitmap ?: warped; warped recycled only if resultBitmap != warped | Correct. |

No remaining known Mat leak in the main paths.

---

## 7. THREADING RISKS

| Area | Thread | Risk |
|------|--------|------|
| **normalizeBitmapOrientation** | Called from Default; performs openInputStream + EXIF read | Blocking IO on Default |
| **processDocument** | Default for compute; withContext(IO) for file write | Correct |
| **ManualCrop confirm** | Default for warp/enhance/OCR; IO for file; Main for callback | Correct |
| **Camera analyzer** | ImageAnalysis executor (Default or custom) | Correct |
| **OpenCV** | Single-threaded use on Default | No concurrent Mat access observed |

---

## 8. COORDINATE SYSTEM FAILURES

- **Preview vs capture:** Capture bitmap is normalized with EXIF before processDocument. Preview analyzer uses rotationDegrees and sets imageWidth/imageHeight from the rotated frame. With normalization, capture and preview are in the same orientation, so scaleX/scaleY are correct for the current design.
- **ManualCrop displayRect:** Computed from BoxWithConstraints and shared with Canvas; mapper uses same displayRect. Consistent for a single frame.
- **Container vs bitmap:** Formulas are correct; drag is clamped to displayRect; convexClampQuad enforces valid quad in bitmap space.
- **Residual:** If any path skipped normalization or used different decode options, preview quad scale would be wrong. No rotation term in CoordinateMapper (not needed for current ManualCrop drawing).

---

## 9. GESTURE PHYSICS ISSUES

- **Drag clamp:** New position is clamped to `displayRect.left/right` and `displayRect.top/bottom` in onDrag. Prevents out-of-bounds and fold onto edges.
- **Convex on end:** convexClampQuad prevents self-intersecting quads from reaching warp; fallback to inset rect can surprise the user.
- **Delta:** Uses `prev + dragAmount`; no double scale or offset error.
- **pointerInput(Unit):** Stable key; no unnecessary recreation.
- **Recomposition:** Each drag updates containerPoints and recomposes overlay and handles; can still cause jitter on low-end devices.

---

## 10. OPENCV RISKS

- **PerspectiveTransformer:** src/dst Mat and transformMatrix released in finally. isValidQuad used before warp. No degenerate quad passed to getPerspectiveTransform in normal flow.
- **DocumentEdgeDetector:** originalMat, resizedMat, and all Mats in detect* passes released in finally.
- **AutoCropProcessor.detectAndCrop:** originalMat, transformedMat, enhancedMat, upscaledMat, etc. released in finally.
- **applyLockletProEnhancement:** try/catch/finally with dest and all intermediates released on throw. B&W branch returns after releasing gray/adaptive; color branch releases in finally. No remaining known leak.

---

## 11. ANR CAUSES

| Cause | Mechanism | Severity |
|-------|------------|----------|
| **Long Default block** | warp (2048) + enhance + OCR in one withContext(Default) in ManualCrop confirm | Medium (target &lt; 800 ms; still possible on slow devices) |
| **IO on Default** | normalizeBitmapOrientation reads stream on Default | Low–Medium |
| **Main thread** | No direct scanner work on Main; UI updates on Main | N/A |

Warp is no longer on full 12MP; file I/O is on IO.

---

## 12. CONFIDENCE LEVELS PER ISSUE

| Issue | Confidence | Notes |
|-------|------------|--------|
| Convex fallback replaces quad | 95% | Code returns inset fullBounds when !isValid |
| normalizeBitmapOrientation IO on Default | 95% | openInputStream + ExifInterface in caller on Default |
| Silent enhance/OCR catch in ManualCrop | 95% | try/catch returning null |
| Preview scale correctness with EXIF | 90% | Depends on all paths applying orientation |
| Otsu/Sobel ordering dependency | 85% | Caller always orders; future reuse could skip |
| Mapper identity at drag end | 75% | Depends on recomposition order |

---

## 13. SEVERITY LEVELS

| Issue | Severity |
|-------|----------|
| Convex fallback replacing user quad | **Medium** |
| normalizeBitmapOrientation on Default (IO) | **Medium** |
| Silent enhance/OCR failure in ManualCrop | **Medium** |
| Recomposition on every drag | **Medium** |
| Long Default block (warp+enhance+OCR) | **Medium** |
| CropQuad.isConvex zero cross | **Low** |
| Otsu/Sobel ordering contract | **Low** |

---

## 14. ARCHITECTURE WEAK POINTS

- **No scanner ViewModel:** State lives in composables; cancellation and cleanup are implicit when the screen is left.
- **normalizeBitmapOrientation call site:** IO is done inside a function called from Default; responsibility for dispatcher is at the caller.
- **Convex fallback semantics:** Fallback is “safe” for warp but not “least surprise” for the user; no in-place correction of the quad.
- **Error handling:** Many catch blocks return null or fallback without user feedback (enhance, OCR, EXIF in normalizeBitmapOrientation).
- **Single pipeline constant:** SCANNER_MAX_DIMENSION (2048) used for decode and downscale; good for consistency; if a path bypassed it, behavior would diverge.

---

## 15. FINAL ROOT CAUSE SUMMARY

1. **Crop geometry:** Convexity and drag clamping are enforced. The main residual issue is convex fallback replacing the entire quad with an inset rectangle when the clamped quad is invalid, which can surprise the user.
2. **Orientation:** EXIF is applied after decode in both ScanDocumentScreen and ManualCropScreen, aligning preview and capture. normalizeBitmapOrientation performs IO on the calling thread (Default), which is a threading smell.
3. **Auto crop:** Detection uses TL/TR/BR/BL ordering, multiple Canny passes, relaxed area ratio, and Otsu/Sobel with ordering in the main flow. Preview quad is used when available; scale is correct when orientation is normalized. Residual: strict thresholds and lighting can still yield null; Otsu/Sobel return raw points and rely on caller to order.
4. **Warp pipeline:** Downscale-before-warp is in place for ManualCrop (decode ≤2048). Degenerate quad validation prevents bad warp input. File I/O is on IO.
5. **Performance:** Warp runs on ≤2048 bitmap; single long Default block (warp + enhance + OCR) and recomposition on every drag remain; IO inside normalizeBitmapOrientation on Default remains.
6. **Memory:** Mat release is correct in PerspectiveTransformer, DocumentEdgeDetector, and AutoCropProcessor (including applyLockletProEnhancement). Bitmap recycle is used where appropriate.
7. **Threading:** processDocument and ManualCrop confirm use Default for compute and IO for file. Main is used for UI. normalizeBitmapOrientation is the only clear “IO on Default” call.
8. **Gesture:** Drag is clamped to display rect; convexClampQuad on end; no out-of-bounds or unclamped delta.
9. **OpenCV:** No remaining Mat leak or missing release in the audited paths; degenerate quad is validated before warp.
10. **Hidden failures:** Silent try/catch in ManualCrop confirm (enhance, OCR) and in normalizeBitmapOrientation (EXIF) hide errors from the user.

**Overall:** The scanner has been stabilized (orientation, convexity, warp size, file IO, corner order, Mat release). Remaining issues are mostly medium severity: convex fallback UX, IO on Default in orientation, silent failures, and recomposition/latency. Addressing these would move the system closer to reference production scanners (Adobe Scan, Microsoft Lens, CamScanner, Google Drive Scanner).

---

**END OF REPORT — DIAGNOSIS ONLY, NO FIXES**

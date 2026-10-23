"""Bounded Tesseract OCR support for uploaded document images."""
from __future__ import annotations

from dataclasses import dataclass, field
import io
import logging
import os
import shutil
import time
from typing import Any
import warnings

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError
except ImportError:  # pragma: no cover - exercised when optional runtime deps are absent.
    Image = None  # type: ignore[assignment]
    ImageEnhance = None  # type: ignore[assignment]
    ImageFilter = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]
    UnidentifiedImageError = Exception  # type: ignore[assignment,misc]

try:
    import pytesseract
except ImportError:  # pragma: no cover - exercised when optional runtime deps are absent.
    pytesseract = None  # type: ignore[assignment]

OCR_LANGUAGE = "eng"
OCR_TIMEOUT_SECONDS = 12
OCR_TOTAL_TIMEOUT_SECONDS = 45
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MIN_OCR_CHARS = 15
MIN_IMAGE_LONG_EDGE = 1500
MAX_IMAGE_LONG_EDGE = 2400

_AVAILABILITY_CACHE: tuple[bool, str | None, float] | None = None
_AVAILABILITY_TTL_SECONDS = 60

_WINDOWS_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
)

PSM_MODES = [6, 11, 12, 3]


def _find_tesseract() -> str | None:
    """Locate a Tesseract binary from env, PATH, or known Windows install paths."""
    env_cmd = os.environ.get("TESSERACT_CMD", "").strip().strip('"').strip("'")
    if env_cmd:
        env_cmd = os.path.expandvars(os.path.expanduser(env_cmd))
        if os.path.isfile(env_cmd):
            return env_cmd

    path_binary = shutil.which("tesseract")
    if path_binary:
        return path_binary

    for candidate in _WINDOWS_TESSERACT_PATHS:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


@dataclass
class OcrAttempt:
    """Record of a single OCR attempt for diagnostics."""

    preprocessing_variant: str
    psm_mode: int
    char_count: int = 0
    word_count: int = 0
    confidence: float | None = None
    text_preview: str = ""


@dataclass
class OcrResult:
    """OCR text and source-level confidence from one image."""

    raw_text: str = ""
    confidence: float | None = None
    word_count: int = 0
    status: str = "success"
    message: str | None = None
    attempts: list[OcrAttempt] = field(default_factory=list)


def _availability() -> tuple[bool, str | None]:
    """Check Tesseract availability with 60-second TTL cache."""
    global _AVAILABILITY_CACHE

    now = time.monotonic()
    if _AVAILABILITY_CACHE is not None:
        cached_available, cached_message, cached_time = _AVAILABILITY_CACHE
        if now - cached_time < _AVAILABILITY_TTL_SECONDS:
            logger.debug("Tesseract availability check served from cache")
            return cached_available, cached_message

    if pytesseract is None:
        logger.debug("Tesseract unavailable: Python dependencies not installed")
        result = (False, "OCR Python dependencies are not installed.")
        _AVAILABILITY_CACHE = (result[0], result[1], now)
        return result

    command = _find_tesseract()
    if command:
        pytesseract.pytesseract.tesseract_cmd = command
        logger.debug(f"Tesseract binary found at: {command}")
    else:
        logger.debug("Tesseract binary not found in PATH or known locations")

    try:
        version = pytesseract.get_tesseract_version()
        logger.debug(f"Tesseract version: {version}")
        languages = pytesseract.get_languages(config="")
        logger.debug(f"Tesseract languages: {languages}")
        if OCR_LANGUAGE not in languages:
            logger.debug(f"Language '{OCR_LANGUAGE}' not available in Tesseract")
            result = (False, "The English OCR language pack is not available.")
            _AVAILABILITY_CACHE = (result[0], result[1], now)
            return result
    except Exception as e:
        logger.debug(f"Tesseract availability check failed: {e}")
        result = (
            False,
            "Tesseract OCR was not found. Install Tesseract or set TESSERACT_CMD.",
        )
        _AVAILABILITY_CACHE = (result[0], result[1], now)
        return result

    logger.debug("Tesseract availability check passed")
    result = (True, None)
    _AVAILABILITY_CACHE = (result[0], result[1], now)
    return result


def tesseract_available() -> bool:
    """Return whether the configured English Tesseract engine can run."""
    return _availability()[0]


def _exif_and_resize(image: Any) -> Any:
    """Apply EXIF transpose and upscale if needed."""
    original_size = image.size
    image = ImageOps.exif_transpose(image).convert("RGB")
    logger.debug(f"Image after EXIF transpose: {image.size} (was {original_size})")

    long_edge = max(image.size)
    if long_edge and long_edge > MAX_IMAGE_LONG_EDGE:
        scale = MAX_IMAGE_LONG_EDGE / long_edge
        new_size = tuple(max(1, round(side * scale)) for side in image.size)
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        image = image.resize(new_size, resampling)
        logger.debug("Image downscaled to the configured OCR maximum dimension.")
    elif long_edge and long_edge < MIN_IMAGE_LONG_EDGE:
        scale = min(MIN_IMAGE_LONG_EDGE / long_edge, 2.5)
        new_size = tuple(max(1, round(side * scale)) for side in image.size)
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        image = image.resize(new_size, resampling)
        logger.debug("Image upscaled for OCR readability.")
    return image


def _prepare_variant_a(image: Any) -> Any:
    """Variant A: EXIF transpose, grayscale, autocontrast."""
    image = _exif_and_resize(image)
    gray = image.convert("L")
    gray = ImageOps.autocontrast(gray)
    return gray


def _prepare_variant_b(image: Any) -> Any:
    """Variant B: EXIF transpose, grayscale, resize to 2000px width, contrast+sharpen."""
    image = _exif_and_resize(image)
    gray = image.convert("L")

    target_width = 2000
    if gray.width < target_width:
        scale = target_width / gray.width
        new_size = (target_width, max(1, round(gray.height * scale)))
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        gray = gray.resize(new_size, resampling)

    if ImageEnhance is not None:
        gray = ImageEnhance.Contrast(gray).enhance(1.5)
        gray = ImageEnhance.Sharpness(gray).enhance(1.3)
    if ImageFilter is not None:
        gray = gray.filter(ImageFilter.SHARPEN)
    return gray


def _prepare_variant_c(image: Any) -> Any:
    """Variant C: EXIF transpose, grayscale, resize, Otsu-like threshold."""
    image = _exif_and_resize(image)
    gray = image.convert("L")

    target_width = 2000
    if gray.width < target_width:
        scale = target_width / gray.width
        new_size = (target_width, max(1, round(gray.height * scale)))
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        gray = gray.resize(new_size, resampling)

    histogram = gray.histogram()
    total_pixels = sum(histogram)
    if total_pixels == 0:
        return gray

    threshold = _otsu_threshold(histogram)
    gray = gray.point(lambda p: 255 if p > threshold else 0, mode="1")
    return gray.convert("L")


def _otsu_threshold(histogram: list[int]) -> int:
    """Compute Otsu's threshold from a grayscale histogram."""
    total = sum(histogram)
    if total == 0:
        return 128

    sum_total = sum(i * h for i, h in enumerate(histogram))
    sum_bg = 0.0
    weight_bg = 0
    max_variance = 0.0
    best_threshold = 128

    for threshold in range(256):
        weight_bg += histogram[threshold]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break

        sum_bg += threshold * histogram[threshold]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg

        variance = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if variance > max_variance:
            max_variance = variance
            best_threshold = threshold

    return best_threshold


_PREPROCESSING_VARIANTS = {
    "A_autocontrast": _prepare_variant_a,
    "B_contrast_sharpen": _prepare_variant_b,
    "C_otsu_threshold": _prepare_variant_c,
}

_prepare_image = _prepare_variant_a


def _open_image(content: bytes) -> Any:
    if Image is None:
        raise RuntimeError("OCR Python dependencies are not installed.")

    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        image = Image.open(io.BytesIO(content))
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("Image dimensions exceed the 40 MP OCR limit.")
        image.load()
    return image


def _reconstruct_lines_from_data(data: dict[str, list[Any]]) -> tuple[str, float | None, int]:
    """Reconstruct text lines from Tesseract data using bounding-box coordinates.

    Groups words by vertical proximity (same line) and sorts by x-coordinate
    to preserve table structure and left-to-right reading order.
    """
    tokens = data.get("text", [])
    tops = data.get("top", [])
    lefts = data.get("left", [])
    heights = data.get("height", [])
    confs = data.get("conf", [])

    word_entries: list[tuple[int, int, int, str, float]] = []
    confidences: list[float] = []

    for i, token in enumerate(tokens):
        token = str(token).strip()
        if not token:
            continue

        try:
            conf = float(confs[i])
        except (TypeError, ValueError, IndexError):
            conf = -1
        if conf >= 0:
            confidences.append(conf)

        try:
            top = int(tops[i])
            left = int(lefts[i])
            height = int(heights[i])
        except (TypeError, ValueError, IndexError):
            top, left, height = 0, 0, 0

        word_entries.append((top, left, height, token, conf))

    if not word_entries:
        return "", None, 0

    word_entries.sort(key=lambda w: (w[0], w[1]))

    lines: list[list[tuple[int, str]]] = []
    line_y_center: list[float] = []

    for top, left, height, token, conf in word_entries:
        y_center = top + height / 2
        matched = False
        for line_idx, line_center in enumerate(line_y_center):
            line_height_estimate = max(height, 20)
            if abs(y_center - line_center) < line_height_estimate * 0.6:
                lines[line_idx].append((left, token))
                matched = True
                break
        if not matched:
            lines.append([(left, token)])
            line_y_center.append(y_center)

    for line in lines:
        line.sort(key=lambda w: w[0])

    raw_text = "\n".join(" ".join(token for _, token in line) for line in lines).strip()
    average = sum(confidences) / len(confidences) if confidences else None
    return raw_text, average, len(confidences)


def _run_ocr_with_psm(
    prepared: Any, psm: int, timeout_seconds: int | None = None
) -> tuple[str, float | None, int]:
    """Run Tesseract with a specific PSM mode and a bounded time budget."""
    data = pytesseract.image_to_data(
        prepared,
        lang=OCR_LANGUAGE,
        config=f"--oem 3 --psm {psm}",
        output_type=pytesseract.Output.DICT,
        timeout=timeout_seconds or OCR_TIMEOUT_SECONDS,
    )
    return _reconstruct_lines_from_data(data)


def _score_ocr_result(text: str, confidence: float | None, word_count: int) -> float:
    """Score an OCR result by confidence and useful content density.

    Higher is better. Penalizes very short results and rewards higher confidence.
    """
    if not text or word_count == 0:
        return 0.0
    conf = confidence if confidence is not None else 50.0
    has_numbers = sum(1 for line in text.splitlines() if any(c.isdigit() for c in line))
    number_bonus = min(has_numbers * 5, 20)
    return conf + number_bonus + min(word_count, 100) * 0.1


def _deduplicate_lines(text: str) -> str:
    """Remove duplicate lines while preserving order."""
    seen: set[str] = set()
    unique_lines: list[str] = []
    for line in text.splitlines():
        normalized = " ".join(line.split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_lines.append(line)
    return "\n".join(unique_lines)


def ocr_image(image: Any) -> OcrResult:
    """Extract text using multi-variant preprocessing and multi-PSM strategy.

    Runs multiple preprocessing variants (autocontrast, contrast+sharpen, Otsu
    threshold) each with multiple PSM modes. Selects the best result by
    confidence + useful content score, not just character count.
    """
    available, reason = _availability()
    if not available:
        return OcrResult(status="unavailable", message=reason)

    attempts: list[OcrAttempt] = []
    best_text = ""
    best_confidence: float | None = None
    best_words = 0
    best_score = 0.0
    started = time.monotonic()
    timed_out = False

    try:
        for variant_name, prepare_fn in _PREPROCESSING_VARIANTS.items():
            try:
                prepared = prepare_fn(image)
            except Exception as e:
                logger.debug(f"Preprocessing variant {variant_name} failed: {e}")
                continue

            logger.debug(f"Variant {variant_name}: prepared image size={prepared.size}")

            for psm in PSM_MODES:
                remaining = OCR_TOTAL_TIMEOUT_SECONDS - (time.monotonic() - started)
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    timeout_seconds = max(1, min(OCR_TIMEOUT_SECONDS, int(remaining)))
                    text, conf, words = _run_ocr_with_psm(prepared, psm, timeout_seconds)
                except RuntimeError as exc:
                    if "timeout" in str(exc).casefold() or "timed out" in str(exc).casefold():
                        timed_out = True
                        break
                    logger.debug("OCR attempt failed with RuntimeError.")
                    continue
                except Exception as exc:
                    logger.debug("OCR attempt failed (%s).", type(exc).__name__)
                    continue

                attempt = OcrAttempt(
                    preprocessing_variant=variant_name,
                    psm_mode=psm,
                    char_count=len(text),
                    word_count=words,
                    confidence=conf,
                    text_preview=text[:200],
                )
                attempts.append(attempt)
                logger.debug(
                    f"OCR {variant_name} PSM {psm}: {len(text)} chars, "
                    f"{words} words, conf={conf}"
                )

                score = _score_ocr_result(text, conf, words)
                if score > best_score:
                    best_score = score
                    best_text = text
                    best_confidence = conf
                    best_words = words
            if timed_out:
                break

        if best_text:
            best_text = _deduplicate_lines(best_text)

    except RuntimeError:
        return OcrResult(
            status="error",
            message="OCR timed out before text could be extracted from this marksheet. "
            "Please upload a clearer scan or enter details manually.",
            attempts=attempts,
        )
    except Exception as e:
        logger.error(f"OCR pipeline error: {e}")
        return OcrResult(
            status="error",
            message="OCR could not read this marksheet. Please upload a higher-resolution "
            "image, ensure the text is upright and well-lit, or enter details manually.",
            attempts=attempts,
        )

    if timed_out and not best_text:
        return OcrResult(
            status="error",
            message="OCR reached its processing time limit before readable text was found. Use a clearer or smaller scan, or enter details manually.",
            attempts=attempts,
        )

    if len(best_text) < MIN_OCR_CHARS:
        return OcrResult(
            raw_text=best_text,
            confidence=best_confidence,
            word_count=best_words,
            status="empty",
            message="No readable text was found in this marksheet. The scan may be blank, "
            "low resolution, or too faint for OCR. Please upload a clearer image or enter "
            "details manually.",
            attempts=attempts,
        )

    logger.info(
        f"OCR complete: {len(best_text)} chars, {best_words} words, "
        f"conf={best_confidence}, {len(attempts)} attempts"
    )
    return OcrResult(
        raw_text=best_text,
        confidence=best_confidence,
        word_count=best_words,
        message="OCR returned partial text after reaching its processing time limit; verify every field manually." if timed_out else None,
        attempts=attempts,
    )


def extract_image_ocr(content: bytes) -> OcrResult:
    """Decode uploaded image bytes and run OCR without leaking decoder errors."""
    if not isinstance(content, bytes) or not content:
        return OcrResult(status="error", message="The uploaded image is empty or invalid.")
    if len(content) > MAX_IMAGE_BYTES:
        return OcrResult(status="error", message="The image is larger than the 10 MB OCR limit.")
    try:
        image = _open_image(content)
    except Exception:
        return OcrResult(
            status="error",
            message="This marksheet image appears corrupt, unreadable, or too large for OCR. "
            "Please upload a fresh image or enter details manually.",
        )

    return ocr_image(image)

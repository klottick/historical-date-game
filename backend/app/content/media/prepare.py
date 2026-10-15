"""Decode bounded originals and create full-composition, metadata-free WebP."""

import hashlib
import io
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.content.media.download import MAX_BYTES, immutable_write
from app.content.media.rights import MediaCandidate, check_candidate
from app.content.schemas import MediaRecord

MAX_PIXELS = 20_000_000
MAX_DIMENSION = 10_000


def prepare_image(
    source: Path, output_dir: Path, metadata: MediaCandidate
) -> MediaRecord:
    codes = check_candidate(metadata)
    if codes:
        raise ValueError(",".join(codes))
    if source.is_symlink() or source.stat().st_size > MAX_BYTES:
        raise ValueError("source_size")
    original = source.read_bytes()
    if hashlib.sha1(original).hexdigest() != metadata.upstream_sha1:
        raise ValueError("upstream_digest_mismatch")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(original)) as image:
                if (
                    image.format not in {"PNG", "JPEG", "WEBP"}
                    or image.width * image.height > MAX_PIXELS
                    or max(image.size) > MAX_DIMENSION
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise ValueError("decode_limits")
                # Never silently strip answer-bearing original image metadata.
                # Its presence is unresolved visual/text safety, so fallback.
                if image.getexif() or set(image.info) - {
                    "dpi",
                    "gamma",
                    "srgb",
                    "loop",
                    "background",
                    "transparency",
                    "aspect",
                }:
                    raise ValueError("unsafe_embedded_metadata")
                image.load()
                normalized = ImageOps.exif_transpose(image).convert("RGB")
                normalized.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                normalized.info.clear()
                output = io.BytesIO()
                normalized.save(output, format="WEBP", quality=85, method=4)
    except (
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
    ) as exc:
        raise ValueError("decode_rejected") from exc
    data = output.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    filename = f"media/{sha}.webp"
    immutable_write(output_dir / filename, data)
    values = {
        field: getattr(metadata, field)
        for field in MediaRecord.model_fields
        if field not in {"sha256", "filename"}
    }
    values["attribution"] += (
        "; Converted to WebP and resized without cropping; adaptation under "
        + metadata.rights_basis
    )
    return MediaRecord(**values, sha256=sha, filename=filename)

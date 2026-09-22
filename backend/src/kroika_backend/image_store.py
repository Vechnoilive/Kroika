"""Small local image store with type and size checks before vision calls."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from kroika_contracts.ports import AIProviderError, ProviderErrorCode


_REF = re.compile(r"img_[a-f0-9]{32}")
_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
_PIL_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
_MAX_IMAGE_PIXELS = 40_000_000


@dataclass(frozen=True, slots=True)
class ImageAsset:
    image_ref: str
    media_type: str
    data: bytes


def _detected_media_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class LocalImageStore:
    def __init__(self, root: Path, max_image_bytes: int = 10 * 1024 * 1024):
        self.root = root
        self.max_image_bytes = max_image_bytes
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._make_private(self.root, 0o700)

    @staticmethod
    def _make_private(path: Path, mode: int) -> None:
        try:
            path.chmod(mode)
        except OSError:
            # Windows ACLs are not represented by POSIX mode bits.
            pass

    def _sanitize(self, data: bytes, media_type: str) -> bytes:
        """Decode and re-encode one still image, applying orientation and dropping metadata."""

        try:
            with Image.open(BytesIO(data)) as source:
                if source.format != _PIL_FORMATS[media_type]:
                    raise ValueError("media type mismatch")
                if source.width * source.height > _MAX_IMAGE_PIXELS:
                    raise ValueError("pixel limit exceeded")
                if getattr(source, "n_frames", 1) != 1:
                    raise ValueError("animated images are unsupported")
                source.load()
                oriented = ImageOps.exif_transpose(source)
                has_alpha = oriented.mode in {"RGBA", "LA"} or "transparency" in oriented.info
                normalized = oriented.convert("RGBA" if has_alpha else "RGB")
                output = BytesIO()
                if media_type == "image/jpeg":
                    normalized.convert("RGB").save(
                        output, format="JPEG", quality=95, optimize=True
                    )
                elif media_type == "image/png":
                    normalized.save(output, format="PNG", optimize=True)
                else:
                    normalized.save(output, format="WEBP", quality=95, method=6)
                sanitized = output.getvalue()
        except (Image.DecompressionBombError, OSError, UnidentifiedImageError, ValueError) as exc:
            raise AIProviderError(
                ProviderErrorCode.INVALID_IMAGE,
                "Изображение повреждено, слишком велико или содержит неподдерживаемую анимацию.",
                False,
            ) from exc
        if not sanitized or len(sanitized) > self.max_image_bytes:
            raise AIProviderError(
                ProviderErrorCode.INVALID_IMAGE,
                f"После безопасной обработки изображение должно быть не больше "
                f"{self.max_image_bytes // (1024 * 1024)} МБ.",
                False,
            )
        return sanitized

    def save_base64(self, data_base64: str, media_type: str) -> ImageAsset:
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AIProviderError(
                ProviderErrorCode.INVALID_IMAGE,
                "Файл изображения повреждён. Выберите его ещё раз.",
                False,
            ) from exc
        if not data or len(data) > self.max_image_bytes:
            raise AIProviderError(
                ProviderErrorCode.INVALID_IMAGE,
                f"Изображение должно быть не больше {self.max_image_bytes // (1024 * 1024)} МБ.",
                False,
            )
        if media_type not in _EXTENSIONS or _detected_media_type(data) != media_type:
            raise AIProviderError(
                ProviderErrorCode.INVALID_IMAGE,
                "Поддерживаются настоящие файлы JPEG, PNG и WebP.",
                False,
            )
        data = self._sanitize(data, media_type)
        image_ref = f"img_{uuid4().hex}"
        path = self.root / f"{image_ref}.{_EXTENSIONS[media_type]}"
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(data)
        self._make_private(temporary, 0o600)
        temporary.replace(path)
        self._make_private(path, 0o600)
        return ImageAsset(image_ref, media_type, data)

    def resolve(self, image_ref: str) -> ImageAsset:
        if _REF.fullmatch(image_ref) is None:
            raise AIProviderError(
                ProviderErrorCode.INVALID_IMAGE,
                "Ссылка на изображение недействительна. Загрузите файл ещё раз.",
                False,
            )
        for media_type, extension in _EXTENSIONS.items():
            path = self.root / f"{image_ref}.{extension}"
            if path.is_file():
                data = path.read_bytes()
                if not data or len(data) > self.max_image_bytes or _detected_media_type(data) != media_type:
                    break
                return ImageAsset(image_ref, media_type, data)
        raise AIProviderError(
            ProviderErrorCode.INVALID_IMAGE,
            "Изображение не найдено. Загрузите файл ещё раз.",
            False,
        )

    def delete(self, image_ref: str) -> bool:
        if _REF.fullmatch(image_ref) is None:
            return False
        removed = False
        for extension in _EXTENSIONS.values():
            path = self.root / f"{image_ref}.{extension}"
            if path.is_file() and not path.is_symlink():
                path.unlink()
                removed = True
        return removed

"""Network image providers.

CloudImageProvider — services exposing the common ``/v1/images/generations``
interface (OpenAI image models and compatible gateways). Model, base URL and
key are configuration; nothing is pinned here beyond a default.

LocalImageProvider — Stable Diffusion servers exposing the AUTOMATIC1111 /
Forge / SD.Next ``/sdapi/v1/txt2img`` API.
"""

from __future__ import annotations

import base64
import os

import httpx

from osamu_dazai.providers.image import ImageProvider, ImageRequest, ImageResult


class ImageProviderError(RuntimeError):
    pass


# Sizes the images API accepts; requests are mapped to the closest aspect ratio.
_CLOUD_SIZES = [(1024, 1024), (1536, 1024), (1024, 1536)]


def closest_size(width: int, height: int, sizes: list[tuple[int, int]] = _CLOUD_SIZES) -> tuple[int, int]:
    target = width / height
    return min(sizes, key=lambda s: abs(s[0] / s[1] - target))


class CloudImageProvider(ImageProvider):
    name = "cloud"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-image-1",
        base_url: str = "https://api.openai.com/v1",
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 300.0,
    ) -> None:
        key = api_key or os.environ.get("DAZAI_IMAGE_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not key and client is None:
            raise ImageProviderError("no image API key (set DAZAI_IMAGE_API_KEY or OPENAI_API_KEY)")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=timeout_s, headers={"Authorization": f"Bearer {key}"})

    async def generate(self, req: ImageRequest) -> ImageResult:
        w, h = closest_size(req.width, req.height)
        prompt = f"{req.prompt}\nStyle: {req.style}" if req.style else req.prompt
        body = {"model": req.model or self.model, "prompt": prompt, "size": f"{w}x{h}", "n": 1}
        r = await self.client.post(f"{self.base_url}/images/generations", json=body)
        if r.status_code >= 400:
            raise ImageProviderError(f"image API error {r.status_code}: {r.text[:300]}")
        item = r.json()["data"][0]
        if "b64_json" in item:
            data = base64.b64decode(item["b64_json"])
        elif "url" in item:
            img = await self.client.get(item["url"])
            img.raise_for_status()
            data = img.content
        else:
            raise ImageProviderError("image API returned neither b64_json nor url")
        return ImageResult(data=data, width=w, height=h, provider=self.name, model=body["model"],
                           revised_prompt=item.get("revised_prompt"))


class LocalImageProvider(ImageProvider):
    name = "local"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:7860",
        *,
        steps: int = 30,
        sampler: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 600.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.steps = steps
        self.sampler = sampler
        self.client = client or httpx.AsyncClient(timeout=timeout_s)

    async def generate(self, req: ImageRequest) -> ImageResult:
        # SD models want multiples of 8
        w, h = (max(64, req.width // 8 * 8), max(64, req.height // 8 * 8))
        body: dict = {
            "prompt": f"{req.prompt}, {req.style}" if req.style else req.prompt,
            "negative_prompt": req.negative_prompt,
            "width": w,
            "height": h,
            "steps": self.steps,
        }
        if self.sampler:
            body["sampler_name"] = self.sampler
        try:
            r = await self.client.post(f"{self.base_url}/sdapi/v1/txt2img", json=body)
        except httpx.HTTPError as e:
            raise ImageProviderError(f"local image server unreachable at {self.base_url}: {e}") from e
        if r.status_code >= 400:
            raise ImageProviderError(f"local image server error {r.status_code}: {r.text[:300]}")
        images = r.json().get("images") or []
        if not images:
            raise ImageProviderError("local image server returned no images")
        return ImageResult(data=base64.b64decode(images[0]), width=w, height=h, provider=self.name,
                           model=req.model or "local-sd")

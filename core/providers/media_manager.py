import cloudinary
import cloudinary.uploader
import logging
import os
import base64
import asyncio
import hashlib
import re
from typing import Optional

logger = logging.getLogger("UniversalAIGateway")

# Capture data:image... pattern
DATA_URI_REGEX = re.compile(r'(data:image/[^;]+;base64,[a-zA-Z0-9+/=]+)')

class MediaManager:
    """Manages media uploads to external storage (Cloudinary) with caching."""

    _initialized = False

    @classmethod
    def _initialize(cls):
        if not cls._initialized:
            # Check for CLOUDINARY_URL in env
            if os.getenv("CLOUDINARY_URL"):
                # Cloudinary auto-configures from this env var
                cls._initialized = True
                logger.info("Cloudinary initialized from environment variable.")
            else:
                logger.warning("CLOUDINARY_URL not found. Media uploads will fail.")

    @classmethod
    async def upload_file(cls, content: bytes, resource_type: str = "auto", redis_client=None) -> Optional[str]:
        """Uploads a file to Cloudinary and returns the secure URL.

        Args:
            content: Raw file bytes.
            resource_type: "image", "video", or "raw" (or "auto").
            redis_client: Optional redis client for caching.

        Returns:
            Public secure URL or None if failed.
        """
        cls._initialize()

        if not cls._initialized:
             logger.error("Cannot upload: Cloudinary not configured.")
             return None

        # Calculate Hash for Cache Key
        file_hash = hashlib.md5(content).hexdigest()
        cache_key = f"media_cache:cloudinary:{file_hash}"

        # Check Cache
        if redis_client:
            cached_url = await redis_client.get(cache_key)
            if cached_url:
                logger.info(f"[Cloudinary Cache] HIT: {cached_url}")
                return cached_url

        try:
            # Cloudinary SDK is synchronous, so we run it in an executor
            # We explicitly pass the content as a byte array/stream
            result = await asyncio.to_thread(
                cloudinary.uploader.upload,
                content,
                resource_type=resource_type,
                folder="magic_proxy_uploads" # Organization folder
            )

            url = result.get("secure_url")
            logger.info(f"[Cloudinary Cache] MISS: Uploaded new media: {url}")

            # Store in Cache (48 hours TTL)
            if redis_client and url:
                await redis_client.setex(cache_key, 172800, url)

            return url

        except Exception as e:
            logger.error(f"Cloudinary upload failed: {e}")
            return None

    @classmethod
    async def process_messages_for_url_provider(cls, messages: list, redis_client=None) -> list:
        """Scans messages for base64 images, uploads them, and replaces with URLs.

        Used for providers like OpenAI/Mistral/Groq that prefer URLs over base64.
        """
        processed_messages = []
        for msg in messages:
            # Deep copy to avoid mutating original request structures if shared
            new_msg = msg.copy()
            content = new_msg.get("content")

            if isinstance(content, list):
                new_content = []
                for item in content:
                    if item.get("type") == "image_url":
                        image_url = item.get("image_url", {}).get("url", "")
                        if image_url.startswith("data:"):
                            # Base64 found
                            try:
                                header, data_str = image_url.split(",", 1)
                                # header example: data:image/jpeg;base64
                                # Extract mime if needed, but Cloudinary detects automatically
                                file_bytes = base64.b64decode(data_str)

                                public_url = await cls.upload_file(
                                    file_bytes,
                                    resource_type="image",
                                    redis_client=redis_client
                                )

                                if public_url:
                                    # Replace with URL item
                                    new_content.append({
                                        "type": "image_url",
                                        "image_url": {"url": public_url}
                                    })
                                else:
                                    # Fallback: keep text error or original?
                                    # Keeping original base64 might crash context, but better than nothing?
                                    # Let's fallback to text error to save context.
                                    new_content.append({"type": "text", "text": "[Image upload failed]"})
                            except Exception as e:
                                logger.error(f"Error processing base64 image: {e}")
                                new_content.append({"type": "text", "text": "[Invalid Image Data]"})
                        else:
                            # Already a URL
                            new_content.append(item)
                    else:
                        new_content.append(item)
                new_msg["content"] = new_content

            elif isinstance(content, str):
                # Check for embedded Base64 strings (e.g. from OpenWebUI)
                # We split the string by the regex
                parts = DATA_URI_REGEX.split(content)
                if len(parts) > 1:
                    new_content = []
                    for part in parts:
                        if part.startswith("data:image"):
                            # It's an image
                            try:
                                header, data_str = part.split(",", 1)
                                file_bytes = base64.b64decode(data_str)
                                public_url = await cls.upload_file(
                                    file_bytes,
                                    resource_type="image",
                                    redis_client=redis_client
                                )
                                if public_url:
                                    new_content.append({
                                        "type": "image_url",
                                        "image_url": {"url": public_url}
                                    })
                                else:
                                    new_content.append({"type": "text", "text": "[Image upload failed]"})
                            except Exception as e:
                                logger.error(f"Error processing embedded base64 image: {e}")
                                new_content.append({"type": "text", "text": "[Invalid Image Data]"})
                        else:
                            # It's text (if not empty)
                            if part.strip():
                                new_content.append({"type": "text", "text": part})
                    new_msg["content"] = new_content

            processed_messages.append(new_msg)
        return processed_messages

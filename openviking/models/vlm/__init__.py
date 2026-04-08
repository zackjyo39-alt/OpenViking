# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""VLM (Vision-Language Model) module"""

from .backends.openai_vlm import OpenAIVLM
from .backends.volcengine_vlm import VolcEngineVLM
from .base import VLMBase, VLMFactory
from .registry import get_all_provider_names, is_valid_provider

try:
    from .backends.litellm_vlm import LiteLLMVLMProvider
except ImportError:
    LiteLLMVLMProvider = None

__all__ = [
    "VLMBase",
    "VLMFactory",
    "OpenAIVLM",
    "VolcEngineVLM",
    "LiteLLMVLMProvider",
    "get_all_provider_names",
    "is_valid_provider",
]

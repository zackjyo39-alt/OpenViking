# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Regression tests for optional LiteLLM imports."""

import importlib
import sys


def test_openai_embedder_import_does_not_require_litellm():
    """Importing the OpenAI embedder should not pull in optional LiteLLM deps."""
    sys.modules.pop("openviking.models.vlm", None)
    sys.modules.pop("openviking.models.vlm.__init__", None)
    sys.modules.pop("openviking.models.embedder.openai_embedders", None)

    module = importlib.import_module("openviking.models.embedder.openai_embedders")

    assert module.OpenAIDenseEmbedder is not None

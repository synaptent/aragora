from __future__ import annotations

import os
from unittest.mock import patch

from aragora.config.validator import validate_all


def test_distributed_state_accepts_sentinel_configuration() -> None:
    with (
        patch.dict(
            os.environ,
            {
                "ARAGORA_ENV": "development",
                "ARAGORA_REDIS_MODE": "sentinel",
                "ARAGORA_REDIS_SENTINEL_HOSTS": "sentinel-1:26379,sentinel-2:26379,sentinel-3:26379",
                "ARAGORA_REDIS_SENTINEL_MASTER": "mymaster",
            },
            clear=True,
        ),
        patch("aragora.config.validator.is_distributed_state_required", return_value=True),
    ):
        result = validate_all(strict=False)

    assert result["config_summary"]["redis_configured"] is True
    assert not any("Distributed state required" in err for err in result["errors"])


def test_distributed_state_without_url_or_sentinel_fails() -> None:
    with (
        patch.dict(os.environ, {"ARAGORA_ENV": "development"}, clear=True),
        patch("aragora.config.validator.is_distributed_state_required", return_value=True),
    ):
        result = validate_all(strict=False)

    assert result["config_summary"]["redis_configured"] is False
    assert any("Distributed state required" in err for err in result["errors"])

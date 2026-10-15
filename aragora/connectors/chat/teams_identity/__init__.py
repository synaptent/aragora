"""Teams user identity bridge (compatibility path).

The bridge lives in :mod:`aragora.auth.teams_identity`. This path resolves to that
same module object, so the shared ``_bridge`` singleton and any patch applied
through either path stay in step.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aragora.auth import teams_identity as _teams_identity

if not TYPE_CHECKING:
    sys.modules[__name__] = _teams_identity

if TYPE_CHECKING:
    from aragora.auth.teams_identity import TEAMS_PROVIDER as TEAMS_PROVIDER
    from aragora.auth.teams_identity import TeamsUserIdentityBridge as TeamsUserIdentityBridge
    from aragora.auth.teams_identity import TeamsUserInfo as TeamsUserInfo
    from aragora.auth.teams_identity import _bridge as _bridge
    from aragora.auth.teams_identity import (
        get_teams_identity_bridge as get_teams_identity_bridge,
    )

"""Mock object fixtures for storage, ELO, agents, and environment (pytest plugin)."""

from unittest.mock import Mock

import pytest


@pytest.fixture
def mock_storage() -> Mock:
    """Create a mock DebateStorage.

    Returns a Mock object with common storage methods pre-configured
    with sensible return values.
    """
    storage = Mock()
    storage.list_debates.return_value = [
        {
            "id": "debate-1",
            "slug": "test-debate",
            "task": "Test task",
            "created_at": "2026-01-05",
        },
        {
            "id": "debate-2",
            "slug": "another-debate",
            "task": "Another task",
            "created_at": "2026-01-04",
        },
    ]
    storage.get_debate.return_value = {
        "id": "debate-1",
        "slug": "test-debate",
        "task": "Test task",
        "messages": [{"agent": "claude", "content": "Hello"}],
        "critiques": [],
        "consensus_reached": False,
        "rounds_used": 3,
    }
    storage.get_debate_by_slug.return_value = storage.get_debate.return_value
    # Debate reads are org-scoped: every id resolves to a private debate of the
    # org the handler test fixtures authenticate as.
    storage.get_access_info.side_effect = lambda ref: (ref, "test-org-001", False)
    return storage


@pytest.fixture
def explainability_org_member(monkeypatch):
    """Requests act for test-org-001, and every debate id is a private debate of that org.

    For explainability handler tests that build decisions from patched storage
    instead of seeding debates with an owner.
    """
    from aragora.billing.auth.context import UserAuthContext
    from aragora.tenancy import debate_access

    user = UserAuthContext(
        authenticated=True, user_id="test-user-001", org_id="test-org-001", role="admin"
    )

    def owned_by_caller_org(storage, ref):
        return debate_access.DebateAccess(debate_id=ref, org_id=user.org_id, is_public=False)

    monkeypatch.setattr(
        "aragora.billing.jwt_auth.extract_user_from_request",
        lambda handler, user_store=None: user,
    )
    monkeypatch.setattr(debate_access, "find_debate_access", owned_by_caller_org)
    monkeypatch.setattr(
        "aragora.server.handlers.decisions.explainability.find_debate_access",
        owned_by_caller_org,
    )
    return user


@pytest.fixture
def mock_elo_system() -> Mock:
    """Create a mock EloSystem.

    Returns a Mock object with common ELO system methods pre-configured.
    """
    elo = Mock()

    # Mock agent rating
    mock_rating = Mock()
    mock_rating.agent_name = "test_agent"
    mock_rating.elo = 1500
    mock_rating.wins = 5
    mock_rating.losses = 3
    mock_rating.draws = 2
    mock_rating.games_played = 10
    mock_rating.win_rate = 0.5
    mock_rating.domain_elos = {}
    mock_rating.debates_count = 10
    mock_rating.critiques_accepted = 5
    mock_rating.critiques_total = 10

    elo.get_rating.return_value = mock_rating
    elo.get_leaderboard.return_value = [mock_rating]
    elo.get_cached_leaderboard.return_value = [
        {
            "agent_name": "test_agent",
            "elo": 1500,
            "wins": 5,
            "losses": 3,
            "draws": 2,
            "games_played": 10,
            "win_rate": 0.5,
        }
    ]
    elo.get_recent_matches.return_value = []
    elo.get_cached_recent_matches.return_value = []
    elo.get_head_to_head.return_value = {
        "matches": 5,
        "agent_a_wins": 2,
        "agent_b_wins": 2,
        "draws": 1,
    }
    elo.get_stats.return_value = {
        "total_agents": 10,
        "total_matches": 50,
        "avg_elo": 1500,
    }
    elo.get_rivals.return_value = []
    elo.get_allies.return_value = []

    return elo


@pytest.fixture
def mock_calibration_tracker() -> Mock:
    """Create a mock CalibrationTracker.

    Returns a Mock object with calibration methods that return
    fast, deterministic values suitable for testing.
    """
    tracker = Mock()

    # Mock calibration summary
    mock_summary = Mock()
    mock_summary.agent = "test_agent"
    mock_summary.total_predictions = 100
    mock_summary.total_correct = 75
    mock_summary.brier_score = 0.15
    mock_summary.ece = 0.08
    mock_summary.adjust_confidence = Mock(side_effect=lambda c, domain=None: c)

    # Configure methods
    tracker.get_calibration_summary.return_value = mock_summary
    tracker.get_brier_score.return_value = 0.15
    tracker.get_expected_calibration_error.return_value = 0.08
    tracker.get_calibration_curve.return_value = []
    tracker.get_all_agents.return_value = ["test_agent"]
    tracker.record_prediction = Mock()
    tracker.record_outcome = Mock()
    tracker.get_temperature_params.return_value = Mock(
        temperature=1.0, get_temperature=Mock(return_value=1.0)
    )

    return tracker


@pytest.fixture
def mock_agent() -> Mock:
    """Create a mock Agent.

    Returns a Mock object representing a debate agent.
    """
    agent = Mock()
    agent.name = "test_agent"
    agent.role = "proposer"
    agent.model = "claude-3-opus"

    async def mock_generate(*args, **kwargs):
        return "This is a test response from the agent."

    agent.generate = mock_generate
    return agent


@pytest.fixture
def mock_agents() -> list[Mock]:
    """Create a list of mock agents for multi-agent tests.

    Returns a list of 3 mock agents with different names.
    """
    agents = []
    for i, name in enumerate(["claude", "gemini", "gpt4"]):
        agent = Mock()
        agent.name = name
        agent.role = "proposer" if i == 0 else "critic"
        agent.model = f"model-{name}"
        agents.append(agent)
    return agents


@pytest.fixture
def mock_environment() -> Mock:
    """Create a mock Environment for arena testing.

    Returns a Mock object with environment properties.
    """
    env = Mock()
    env.task = "Test debate task"
    env.context = ""
    env.max_rounds = 5
    return env


@pytest.fixture
def mock_emitter() -> Mock:
    """Create a mock event emitter.

    Returns a Mock object that can be used as an event emitter.
    """
    emitter = Mock()
    emitter.emit = Mock()
    emitter.subscribe = Mock()
    emitter.unsubscribe = Mock()
    return emitter

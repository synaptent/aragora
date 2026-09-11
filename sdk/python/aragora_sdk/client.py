"""
Aragora API Client

Main HTTP client for interacting with the Aragora platform.
"""

from __future__ import annotations

import os
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from math import ceil
from threading import TIMEOUT_MAX
from typing import TYPE_CHECKING, Any, Literal, cast, overload
from urllib.parse import urljoin

if TYPE_CHECKING:
    from .websocket import AragoraWebSocket

import httpx

from .exceptions import (
    AragoraError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)


def _parse_retry_after(value: str | None) -> int | None:
    """Return an HTTP retry hint representable by the platform's timeout machinery."""
    if value is None:
        return None
    value = value.strip()
    try:
        if value.isascii() and value.isdecimal():
            delay = int(value)
        else:
            retry_at = parsedate_to_datetime(value)
            # The obsolete HTTP asctime form has no timezone but always means UTC.
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            delay = max(0, ceil(retry_at.timestamp() - time.time()))
        # This is a representability check, not a retry-policy delay cap. Avoid
        # losing RateLimitError to an overflow in sleep on an unusable hint.
        return delay if delay <= TIMEOUT_MAX else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


class AragoraClient:
    """
    Synchronous Aragora API client.

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai", api_key="your-key")
        >>> debate = client.debates.create(task="Should we adopt microservices?")
        >>> print(debate.debate_id)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_key: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        demo: bool = False,
    ):
        """
        Initialize the Aragora client.

        Args:
            base_url: Base URL of the Aragora API (e.g., "https://api.aragora.ai")
            api_key: API key for authentication (optional for some endpoints)
            timeout: Request timeout in seconds (default: 30)
            max_retries: Maximum number of retries for failed requests (default: 3)
            retry_delay: Base delay between retries in seconds (default: 1.0)
            demo: If True, return mock responses without connecting to a server.
                  No API keys or running server required.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.demo = demo

        if not demo:
            self._client = httpx.Client(
                timeout=timeout,
                headers=self._build_headers(),
            )
        else:
            self._client = None  # type: ignore[assignment]

        # Initialize namespace APIs
        self._init_namespaces()

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        retry_delay: float | None = None,
        demo: bool | None = None,
    ) -> AragoraClient:
        """
        Create a client configured from environment variables.

        Environment variables:
            ARAGORA_API_URL: Base URL (default: http://localhost:8080)
            ARAGORA_API_KEY: API key for authentication
            ARAGORA_TIMEOUT: Request timeout in seconds (default: 30)
            ARAGORA_MAX_RETRIES: Max retries (default: 3)
            ARAGORA_RETRY_DELAY: Base retry delay in seconds (default: 1.0)
            ARAGORA_DEMO: Set to "1" or "true" for demo mode (no server required)

        Explicit keyword arguments override environment variables.

        Example:
            >>> client = AragoraClient.from_env()
            >>> client = AragoraClient.from_env(demo=True)
        """
        if demo is None:
            demo = os.environ.get("ARAGORA_DEMO", "").lower() in ("1", "true", "yes")
        return cls(
            base_url=base_url or os.environ.get("ARAGORA_API_URL", "http://localhost:8080"),
            api_key=api_key or os.environ.get("ARAGORA_API_KEY"),
            timeout=timeout
            if timeout is not None
            else float(os.environ.get("ARAGORA_TIMEOUT", "30")),
            max_retries=max_retries
            if max_retries is not None
            else int(os.environ.get("ARAGORA_MAX_RETRIES", "3")),
            retry_delay=retry_delay
            if retry_delay is not None
            else float(os.environ.get("ARAGORA_RETRY_DELAY", "1.0")),
            demo=demo,
        )

    @property
    def namespaces(self) -> list[str]:
        """List available API namespace names."""
        return sorted(
            name
            for name in dir(self)
            if not name.startswith("_")
            and name
            not in (
                "base_url",
                "api_key",
                "timeout",
                "max_retries",
                "retry_delay",
                "demo",
                "close",
                "request",
                "namespaces",
            )
            and hasattr(getattr(self, name, None), "_client")
        )

    def _build_headers(self) -> dict[str, str]:
        """Build default headers for requests."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "aragora-python-sdk/2.6.3",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _init_namespaces(self) -> None:
        """Initialize namespace API objects."""
        from .namespaces.a2a import A2AAPI
        from .namespaces.accounting import AccountingAPI
        from .namespaces.actions import ActionsAPI
        from .namespaces.admin import AdminAPI
        from .namespaces.advertising import AdvertisingAPI
        from .namespaces.agent_bridge import AgentBridgeAPI
        from .namespaces.agent_dashboard import AgentDashboardAPI
        from .namespaces.agent_selection import AgentSelectionAPI
        from .namespaces.agents import AgentsAPI
        from .namespaces.analytics import AnalyticsAPI
        from .namespaces.ap_automation import APAutomationAPI
        from .namespaces.approvals import ApprovalsAPI
        from .namespaces.ar_automation import ARAutomationAPI
        from .namespaces.audience import AudienceAPI
        from .namespaces.audio import AudioAPI
        from .namespaces.audit import AuditAPI
        from .namespaces.audit_trail import AuditTrailAPI
        from .namespaces.auditing import AuditingAPI
        from .namespaces.auth import AuthAPI
        from .namespaces.autonomous import AutonomousAPI
        from .namespaces.backups import BackupsAPI
        from .namespaces.batch import BatchAPI
        from .namespaces.belief import BeliefAPI
        from .namespaces.belief_network import BeliefNetworkAPI
        from .namespaces.benchmarks import BenchmarksAPI
        from .namespaces.billing import BillingAPI
        from .namespaces.blockchain import BlockchainAPI
        from .namespaces.bots import BotsAPI
        from .namespaces.breakpoints import BreakpointsAPI
        from .namespaces.budgets import BudgetsAPI
        from .namespaces.calibration import CalibrationAPI
        from .namespaces.canvas import CanvasAPI
        from .namespaces.channels import ChannelsAPI
        from .namespaces.chat import ChatAPI
        from .namespaces.checkpoints import CheckpointsAPI
        from .namespaces.classify import ClassifyAPI
        from .namespaces.code_review import CodeReviewAPI
        from .namespaces.codebase import CodebaseAPI
        from .namespaces.compliance import ComplianceAPI
        from .namespaces.computer_use import ComputerUseAPI
        from .namespaces.connectors import ConnectorsAPI
        from .namespaces.consensus import ConsensusAPI
        from .namespaces.context import ContextAPI
        from .namespaces.control_plane import ControlPlaneAPI
        from .namespaces.coordination import CoordinationAPI
        from .namespaces.cost_management import CostManagementAPI
        from .namespaces.costs import CostsAPI
        from .namespaces.critiques import CritiquesAPI
        from .namespaces.crm import CRMAPI
        from .namespaces.cross_pollination import CrossPollinationAPI
        from .namespaces.dag_operations import DAGOperationsAPI
        from .namespaces.dashboard import DashboardAPI
        from .namespaces.debates import DebatesAPI
        from .namespaces.decisions import DecisionsAPI
        from .namespaces.deliberations import DeliberationsAPI
        from .namespaces.dependency_analysis import DependencyAnalysisAPI
        from .namespaces.devices import DevicesAPI
        from .namespaces.devops import DevopsAPI
        from .namespaces.disaster_recovery import DisasterRecoveryAPI
        from .namespaces.documents import DocumentsAPI
        from .namespaces.ecommerce import EcommerceAPI
        from .namespaces.email_debate import EmailDebateAPI
        from .namespaces.email_priority import EmailPriorityAPI
        from .namespaces.email_services import EmailServicesAPI
        from .namespaces.evaluation import EvaluationAPI
        from .namespaces.evolution import EvolutionAPI
        from .namespaces.expenses import ExpensesAPI
        from .namespaces.explainability import ExplainabilityAPI
        from .namespaces.external_agents import ExternalAgentsAPI
        from .namespaces.facts import FactsAPI
        from .namespaces.feature_flags import FeatureFlagsAPI
        from .namespaces.features import FeaturesAPI
        from .namespaces.feedback import FeedbackAPI
        from .namespaces.flips import FlipsAPI
        from .namespaces.gateway import GatewayAPI
        from .namespaces.gauntlet import GauntletAPI
        from .namespaces.genesis import GenesisAPI
        from .namespaces.github import GithubAPI
        from .namespaces.gmail import GmailAPI
        from .namespaces.graph_debates import GraphDebatesAPI
        from .namespaces.health import HealthAPI
        from .namespaces.history import HistoryAPI
        from .namespaces.hybrid_debates import HybridDebatesAPI
        from .namespaces.ideas import IdeasAPI
        from .namespaces.inbox_command import InboxCommandAPI
        from .namespaces.index import IndexAPI
        from .namespaces.insights import InsightsAPI
        from .namespaces.integrations import IntegrationsAPI
        from .namespaces.introspection import IntrospectionAPI
        from .namespaces.invoice_processing import InvoiceProcessingAPI
        from .namespaces.knowledge import KnowledgeAPI
        from .namespaces.knowledge_chat import KnowledgeChatAPI
        from .namespaces.laboratory import LaboratoryAPI
        from .namespaces.leaderboard import LeaderboardAPI
        from .namespaces.learning import LearningAPI
        from .namespaces.marketplace import MarketplaceAPI
        from .namespaces.matches import MatchesAPI
        from .namespaces.matrix_debates import MatrixDebatesAPI
        from .namespaces.mcp import MCPAPI
        from .namespaces.media import MediaAPI
        from .namespaces.memory import MemoryAPI
        from .namespaces.metrics import MetricsAPI
        from .namespaces.ml import MLAPI
        from .namespaces.moderation import ModerationAPI
        from .namespaces.modes import ModesAPI
        from .namespaces.moments import MomentsAPI
        from .namespaces.monitoring import MonitoringAPI
        from .namespaces.n8n import N8nAPI
        from .namespaces.nomic import NomicAPI
        from .namespaces.notifications import NotificationsAPI
        from .namespaces.oauth import OAuthAPI
        from .namespaces.oauth_wizard import OAuthWizardAPI
        from .namespaces.onboarding import OnboardingAPI
        from .namespaces.openapi import OpenApiAPI
        from .namespaces.openclaw import OpenclawAPI
        from .namespaces.orchestration import OrchestrationAPI
        from .namespaces.orchestration_canvas import OrchestrationCanvasAPI
        from .namespaces.organizations import OrganizationsAPI
        from .namespaces.outcomes import OutcomesAPI
        from .namespaces.outlook import OutlookAPI
        from .namespaces.partner import PartnerAPI
        from .namespaces.payments import PaymentsAPI
        from .namespaces.persona import PersonaAPI
        from .namespaces.pipeline import PipelineAPI
        from .namespaces.pipeline_transitions import PipelineTransitionsAPI
        from .namespaces.plans import PlansAPI
        from .namespaces.playbooks import PlaybooksAPI
        from .namespaces.playground import PlaygroundAPI
        from .namespaces.plugins import PluginsAPI
        from .namespaces.podcast import PodcastAPI
        from .namespaces.policies import PoliciesAPI
        from .namespaces.privacy import PrivacyAPI
        from .namespaces.probes import ProbesAPI
        from .namespaces.prompt_engine import PromptEngineAPI
        from .namespaces.pulse import PulseAPI
        from .namespaces.queue import QueueAPI
        from .namespaces.quotas import QuotasAPI
        from .namespaces.ranking import RankingAPI
        from .namespaces.rbac import RBACAPI
        from .namespaces.readiness import ReadinessAPI
        from .namespaces.receipts import ReceiptsAPI
        from .namespaces.reconciliation import ReconciliationAPI
        from .namespaces.relationships import RelationshipsAPI
        from .namespaces.replays import ReplaysAPI
        from .namespaces.repository import RepositoryAPI
        from .namespaces.reputation import ReputationAPI
        from .namespaces.retention import RetentionAPI
        from .namespaces.review_queue import ReviewQueueAPI
        from .namespaces.reviews import ReviewsAPI
        from .namespaces.rlm import RLMAPI
        from .namespaces.routing import RoutingAPI
        from .namespaces.scim import SCIMAPI
        from .namespaces.search import SearchAPI
        from .namespaces.security import SecurityAPI
        from .namespaces.selection import SelectionAPI
        from .namespaces.self_improve import SelfImproveAPI
        from .namespaces.services import ServicesAPI
        from .namespaces.settlements import SettlementAPI
        from .namespaces.shared_inbox import SharedInboxAPI
        from .namespaces.skills import SkillsAPI
        from .namespaces.slo import SLOAPI
        from .namespaces.sme import SMEAPI
        from .namespaces.social import SocialAPI
        from .namespaces.spectate import SpectateAPI
        from .namespaces.sso import SSOAPI
        from .namespaces.status import StatusAPI
        from .namespaces.support import SupportAPI
        from .namespaces.system import SystemAPI
        from .namespaces.tasks import TasksAPI
        from .namespaces.teams import TeamsAPI
        from .namespaces.templates import TemplatesAPI
        from .namespaces.tenants import TenantsAPI
        from .namespaces.threat_intel import ThreatIntelAPI
        from .namespaces.tournaments import TournamentsAPI
        from .namespaces.training import TrainingAPI
        from .namespaces.transcription import TranscriptionAPI
        from .namespaces.uncertainty import UncertaintyAPI
        from .namespaces.unified_inbox import UnifiedInboxAPI
        from .namespaces.usage import UsageAPI
        from .namespaces.usage_metering import UsageMeteringAPI
        from .namespaces.users import UsersAPI
        from .namespaces.verification import VerificationAPI
        from .namespaces.verticals import VerticalsAPI
        from .namespaces.voice import VoiceAPI
        from .namespaces.webhooks import WebhooksAPI
        from .namespaces.workflow_templates import WorkflowTemplatesAPI
        from .namespaces.workflows import WorkflowsAPI
        from .namespaces.workspace_settings import WorkspaceSettingsAPI
        from .namespaces.workspaces import WorkspacesAPI
        from .namespaces.youtube import YouTubeAPI

        self.a2a = A2AAPI(self)
        self.accounting = AccountingAPI(self)
        self.actions = ActionsAPI(self)
        self.admin = AdminAPI(self)
        self.agent_bridge = AgentBridgeAPI(self)
        self.advertising = AdvertisingAPI(self)
        self.agent_dashboard = AgentDashboardAPI(self)
        self.agent_selection = AgentSelectionAPI(self)
        self.agents = AgentsAPI(self)
        self.analytics = AnalyticsAPI(self)
        self.ap_automation = APAutomationAPI(self)
        self.approvals = ApprovalsAPI(self)
        self.ar_automation = ARAutomationAPI(self)
        self.audience = AudienceAPI(self)
        self.audio = AudioAPI(self)
        self.audit = AuditAPI(self)
        self.audit_trail = AuditTrailAPI(self)
        self.auditing = AuditingAPI(self)
        self.auth = AuthAPI(self)
        self.autonomous = AutonomousAPI(self)
        self.backups = BackupsAPI(self)
        self.batch = BatchAPI(self)
        self.belief = BeliefAPI(self)
        self.belief_network = BeliefNetworkAPI(self)
        self.benchmarks = BenchmarksAPI(self)
        self.bots = BotsAPI(self)
        self.breakpoints = BreakpointsAPI(self)
        self.billing = BillingAPI(self)
        self.budgets = BudgetsAPI(self)
        self.blockchain = BlockchainAPI(self)
        self.calibration = CalibrationAPI(self)
        self.canvas = CanvasAPI(self)
        self.channels = ChannelsAPI(self)
        self.chat = ChatAPI(self)
        self.dag_operations = DAGOperationsAPI(self)
        self.pipeline = PipelineAPI(self)
        self.pipeline_transitions = PipelineTransitionsAPI(self)
        self.playground = PlaygroundAPI(self)
        self.checkpoints = CheckpointsAPI(self)
        self.classify = ClassifyAPI(self)
        self.code_review = CodeReviewAPI(self)
        self.codebase = CodebaseAPI(self)
        self.compliance = ComplianceAPI(self)
        self.computer_use = ComputerUseAPI(self)
        self.connectors = ConnectorsAPI(self)
        self.consensus = ConsensusAPI(self)
        self.context = ContextAPI(self)
        self.control_plane = ControlPlaneAPI(self)
        self.coordination = CoordinationAPI(self)
        self.cost_management = CostManagementAPI(self)
        self.costs = CostsAPI(self)
        self.critiques = CritiquesAPI(self)
        self.crm = CRMAPI(self)
        self.cross_pollination = CrossPollinationAPI(self)
        self.dashboard = DashboardAPI(self)
        self.debates = DebatesAPI(self)
        self.decisions = DecisionsAPI(self)
        self.deliberations = DeliberationsAPI(self)
        self.dependency_analysis = DependencyAnalysisAPI(self)
        self.devops = DevopsAPI(self)
        self.devices = DevicesAPI(self)
        self.disaster_recovery = DisasterRecoveryAPI(self)
        self.documents = DocumentsAPI(self)
        self.ecommerce = EcommerceAPI(self)
        self.email_debate = EmailDebateAPI(self)
        self.email_priority = EmailPriorityAPI(self)
        self.email_services = EmailServicesAPI(self)
        self.evaluation = EvaluationAPI(self)
        self.evolution = EvolutionAPI(self)
        self.expenses = ExpensesAPI(self)
        self.explainability = ExplainabilityAPI(self)
        self.external_agents = ExternalAgentsAPI(self)
        self.facts = FactsAPI(self)
        self.feature_flags = FeatureFlagsAPI(self)
        self.features = FeaturesAPI(self)
        self.feedback = FeedbackAPI(self)
        self.flips = FlipsAPI(self)
        self.gateway = GatewayAPI(self)
        self.gauntlet = GauntletAPI(self)
        self.genesis = GenesisAPI(self)
        self.github = GithubAPI(self)
        self.gmail = GmailAPI(self)
        self.graph_debates = GraphDebatesAPI(self)
        self.health = HealthAPI(self)
        self.history = HistoryAPI(self)
        self.hybrid_debates = HybridDebatesAPI(self)
        self.inbox_command = InboxCommandAPI(self)
        self.ideas = IdeasAPI(self)
        self.index = IndexAPI(self)
        self.integrations = IntegrationsAPI(self)
        self.insights = InsightsAPI(self)
        self.introspection = IntrospectionAPI(self)
        self.invoice_processing = InvoiceProcessingAPI(self)
        self.knowledge = KnowledgeAPI(self)
        self.knowledge_chat = KnowledgeChatAPI(self)
        self.laboratory = LaboratoryAPI(self)
        self.leaderboard = LeaderboardAPI(self)
        self.learning = LearningAPI(self)
        self.marketplace = MarketplaceAPI(self)
        self.memory = MemoryAPI(self)
        self.matches = MatchesAPI(self)
        self.mcp = MCPAPI(self)
        self.matrix_debates = MatrixDebatesAPI(self)
        self.media = MediaAPI(self)
        self.metrics = MetricsAPI(self)
        self.ml = MLAPI(self)
        self.moderation = ModerationAPI(self)
        self.modes = ModesAPI(self)
        self.moments = MomentsAPI(self)
        self.monitoring = MonitoringAPI(self)
        self.n8n = N8nAPI(self)
        self.nomic = NomicAPI(self)
        self.notifications = NotificationsAPI(self)
        self.oauth = OAuthAPI(self)
        self.oauth_wizard = OAuthWizardAPI(self)
        self.openclaw = OpenclawAPI(self)
        self.openapi = OpenApiAPI(self)
        self.outcomes = OutcomesAPI(self)
        self.orchestration = OrchestrationAPI(self)
        self.orchestration_canvas = OrchestrationCanvasAPI(self)
        self.onboarding = OnboardingAPI(self)
        self.organizations = OrganizationsAPI(self)
        self.outlook = OutlookAPI(self)
        self.partner = PartnerAPI(self)
        self.payments = PaymentsAPI(self)
        self.persona = PersonaAPI(self)
        self.plans = PlansAPI(self)
        self.playbooks = PlaybooksAPI(self)
        self.plugins = PluginsAPI(self)
        self.podcast = PodcastAPI(self)
        self.policies = PoliciesAPI(self)
        self.privacy = PrivacyAPI(self)
        self.prompt_engine = PromptEngineAPI(self)
        self.probes = ProbesAPI(self)
        self.pulse = PulseAPI(self)
        self.queue = QueueAPI(self)
        self.quotas = QuotasAPI(self)
        self.reconciliation = ReconciliationAPI(self)
        self.ranking = RankingAPI(self)
        self.rbac = RBACAPI(self)
        self.readiness = ReadinessAPI(self)
        self.receipts = ReceiptsAPI(self)
        self.reputation = ReputationAPI(self)
        self.retention = RetentionAPI(self)
        self.reviews = ReviewsAPI(self)
        self.relationships = RelationshipsAPI(self)
        self.replays = ReplaysAPI(self)
        self.review_queue = ReviewQueueAPI(self)
        self.repository = RepositoryAPI(self)
        self.rlm = RLMAPI(self)
        self.routing = RoutingAPI(self)
        self.scim = SCIMAPI(self)
        self.search = SearchAPI(self)
        self.security = SecurityAPI(self)
        self.settlements = SettlementAPI(self)
        self.selection = SelectionAPI(self)
        self.self_improve = SelfImproveAPI(self)
        self.services = ServicesAPI(self)
        self.shared_inbox = SharedInboxAPI(self)
        self.skills = SkillsAPI(self)
        self.slo = SLOAPI(self)
        self.sme = SMEAPI(self)
        self.social = SocialAPI(self)
        self.spectate = SpectateAPI(self)
        self.status = StatusAPI(self)
        self.sso = SSOAPI(self)
        self.support = SupportAPI(self)
        self.system = SystemAPI(self)
        self.tasks = TasksAPI(self)
        self.teams = TeamsAPI(self)
        self.templates = TemplatesAPI(self)
        self.tenants = TenantsAPI(self)
        self.training = TrainingAPI(self)
        self.transcription = TranscriptionAPI(self)
        self.threat_intel = ThreatIntelAPI(self)
        self.tournaments = TournamentsAPI(self)
        self.uncertainty = UncertaintyAPI(self)
        self.unified_inbox = UnifiedInboxAPI(self)
        self.usage = UsageAPI(self)
        self.usage_metering = UsageMeteringAPI(self)
        self.users = UsersAPI(self)
        self.verification = VerificationAPI(self)
        self.verticals = VerticalsAPI(self)
        self.voice = VoiceAPI(self)
        self.webhooks = WebhooksAPI(self)
        self.workflow_templates = WorkflowTemplatesAPI(self)
        self.workflows = WorkflowsAPI(self)
        self.workspace_settings = WorkspaceSettingsAPI(self)
        self.workspaces = WorkspacesAPI(self)
        self.youtube = YouTubeAPI(self)

    @overload
    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        *,
        response_format: Literal["json"] = "json",
    ) -> dict[str, Any]: ...

    @overload
    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        *,
        response_format: Literal["text"],
    ) -> str: ...

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        *,
        response_format: Literal["json", "text"] = "json",
    ) -> dict[str, Any] | str:
        """
        Make an HTTP request to the Aragora API.

        In demo mode, returns mock data without making network calls.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            path: API path (e.g., "/api/v1/debates")
            params: Query parameters
            json: JSON body for POST/PUT requests
            headers: Additional headers
            response_format: Parse the response as JSON or return its text body

        Returns:
            Parsed JSON response as a dictionary.

        Raises:
            AragoraError: For API errors
        """
        if self.demo:
            from .demo import demo_request

            result = demo_request(method, path, params=params, json=json, headers=headers)
            if response_format == "text":
                if isinstance(result, str):
                    return result
                # Mirror the live API: a deployment without this text resource
                # (e.g. no ODR signing key in demo mode) answers 404.
                raise NotFoundError(f"Demo mode has no text response for '{path}'")
            return result

        url = urljoin(self.base_url, path)
        request_headers = {**self._build_headers(), **(headers or {})}

        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = self._client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json,
                    headers=request_headers,
                )

                if response.is_success:
                    if response_format == "text":
                        return response.text
                    if response.content:
                        return cast(dict[str, Any], response.json())
                    return {}

                # Handle error responses
                self._handle_error_response(response)

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2**attempt))
                    continue
                raise AragoraError("Request timed out") from e

            except httpx.ConnectError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2**attempt))
                    continue
                raise AragoraError("Connection failed") from e

            except RateLimitError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    # Use server-specified retry delay if available
                    delay = (
                        e.retry_after
                        if e.retry_after is not None
                        else self.retry_delay * (2**attempt)
                    )
                    time.sleep(delay)
                    continue
                raise

        if last_error:
            raise AragoraError(f"Request failed after {self.max_retries} retries") from last_error

        raise AragoraError("Unexpected error")

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Backward-compatible alias for request()."""
        return self.request(method, path, params=params, json=json, headers=headers)

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Handle error responses and raise appropriate exceptions."""
        try:
            body = response.json()
            message = body.get("error", body.get("message", response.text))
            error_code = body.get("code")
            trace_id = body.get("trace_id")
        except (ValueError, AttributeError):
            body = None
            message = response.text or "Unknown error"
            error_code = None
            trace_id = None

        status = response.status_code

        if status == 401:
            raise AuthenticationError(
                message, error_code=error_code, trace_id=trace_id, response_body=body
            )
        elif status == 403:
            raise AuthorizationError(
                message, error_code=error_code, trace_id=trace_id, response_body=body
            )
        elif status == 404:
            raise NotFoundError(
                message, error_code=error_code, trace_id=trace_id, response_body=body
            )
        elif status == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitError(
                message,
                retry_after=_parse_retry_after(retry_after),
                error_code=error_code,
                trace_id=trace_id,
                response_body=body,
            )
        elif status == 400:
            errors = body.get("errors") if body else None
            raise ValidationError(
                message,
                errors=errors,
                error_code=error_code,
                trace_id=trace_id,
                response_body=body,
            )
        elif status >= 500:
            raise ServerError(
                message,
                status_code=status,
                error_code=error_code,
                trace_id=trace_id,
                response_body=body,
            )
        else:
            raise AragoraError(
                message,
                status_code=status,
                error_code=error_code,
                trace_id=trace_id,
                response_body=body,
            )

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()

    def __enter__(self) -> AragoraClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class AragoraAsyncClient:
    """
    Asynchronous Aragora API client.

    Example:
        >>> async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
        ...     debate = await client.debates.create(task="Should we adopt microservices?")
        ...     print(debate.debate_id)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_key: str | None = None,
        ws_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        demo: bool = False,
    ):
        """
        Initialize the async Aragora client.

        Args:
            base_url: Base URL of the Aragora API
            api_key: API key for authentication
            ws_url: Explicit WebSocket URL (derived from base_url if None)
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries
            retry_delay: Base delay between retries
            demo: If True, return mock responses without connecting to a server.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.ws_url = ws_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.demo = demo

        if not demo:
            self._client = httpx.AsyncClient(
                timeout=timeout,
                headers=self._build_headers(),
            )
        else:
            self._client = None  # type: ignore[assignment]

        # WebSocket client (created lazily)
        self._stream: AragoraWebSocket | None = None

        # Initialize namespace APIs
        self._init_namespaces()

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        ws_url: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        retry_delay: float | None = None,
        demo: bool | None = None,
    ) -> AragoraAsyncClient:
        """
        Create an async client configured from environment variables.

        Environment variables:
            ARAGORA_API_URL: Base URL (default: http://localhost:8080)
            ARAGORA_API_KEY: API key for authentication
            ARAGORA_WS_URL: WebSocket URL (derived from base_url if not set)
            ARAGORA_TIMEOUT: Request timeout in seconds (default: 30)
            ARAGORA_MAX_RETRIES: Max retries (default: 3)
            ARAGORA_RETRY_DELAY: Base retry delay in seconds (default: 1.0)
            ARAGORA_DEMO: Set to "1" or "true" for demo mode

        Explicit keyword arguments override environment variables.

        Example:
            >>> async with AragoraAsyncClient.from_env(demo=True) as client:
            ...     debate = await client.debates.create(task="Evaluate options")
        """
        if demo is None:
            demo = os.environ.get("ARAGORA_DEMO", "").lower() in ("1", "true", "yes")
        return cls(
            base_url=base_url or os.environ.get("ARAGORA_API_URL", "http://localhost:8080"),
            api_key=api_key or os.environ.get("ARAGORA_API_KEY"),
            ws_url=ws_url or os.environ.get("ARAGORA_WS_URL"),
            timeout=timeout
            if timeout is not None
            else float(os.environ.get("ARAGORA_TIMEOUT", "30")),
            max_retries=max_retries
            if max_retries is not None
            else int(os.environ.get("ARAGORA_MAX_RETRIES", "3")),
            retry_delay=retry_delay
            if retry_delay is not None
            else float(os.environ.get("ARAGORA_RETRY_DELAY", "1.0")),
            demo=demo,
        )

    def _build_headers(self) -> dict[str, str]:
        """Build default headers for requests."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "aragora-python-sdk/2.6.3",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _init_namespaces(self) -> None:
        """Initialize namespace API objects."""
        from .namespaces.a2a import AsyncA2AAPI
        from .namespaces.accounting import AsyncAccountingAPI
        from .namespaces.actions import AsyncActionsAPI
        from .namespaces.admin import AsyncAdminAPI
        from .namespaces.advertising import AsyncAdvertisingAPI
        from .namespaces.agent_bridge import AsyncAgentBridgeAPI
        from .namespaces.agent_dashboard import AsyncAgentDashboardAPI
        from .namespaces.agent_selection import AsyncAgentSelectionAPI
        from .namespaces.agents import AsyncAgentsAPI
        from .namespaces.analytics import AsyncAnalyticsAPI
        from .namespaces.ap_automation import AsyncAPAutomationAPI
        from .namespaces.approvals import AsyncApprovalsAPI
        from .namespaces.ar_automation import AsyncARAutomationAPI
        from .namespaces.audience import AsyncAudienceAPI
        from .namespaces.audio import AsyncAudioAPI
        from .namespaces.audit import AsyncAuditAPI
        from .namespaces.audit_trail import AsyncAuditTrailAPI
        from .namespaces.auditing import AsyncAuditingAPI
        from .namespaces.auth import AsyncAuthAPI
        from .namespaces.autonomous import AsyncAutonomousAPI
        from .namespaces.backups import AsyncBackupsAPI
        from .namespaces.batch import AsyncBatchAPI
        from .namespaces.belief import AsyncBeliefAPI
        from .namespaces.belief_network import AsyncBeliefNetworkAPI
        from .namespaces.billing import AsyncBillingAPI
        from .namespaces.blockchain import AsyncBlockchainAPI
        from .namespaces.bots import AsyncBotsAPI
        from .namespaces.budgets import AsyncBudgetsAPI
        from .namespaces.calibration import AsyncCalibrationAPI
        from .namespaces.canvas import AsyncCanvasAPI
        from .namespaces.chat import AsyncChatAPI
        from .namespaces.checkpoints import AsyncCheckpointsAPI
        from .namespaces.classify import AsyncClassifyAPI
        from .namespaces.code_review import AsyncCodeReviewAPI
        from .namespaces.codebase import AsyncCodebaseAPI
        from .namespaces.compliance import AsyncComplianceAPI
        from .namespaces.computer_use import AsyncComputerUseAPI
        from .namespaces.connectors import AsyncConnectorsAPI
        from .namespaces.consensus import AsyncConsensusAPI
        from .namespaces.control_plane import AsyncControlPlaneAPI
        from .namespaces.coordination import AsyncCoordinationAPI
        from .namespaces.cost_management import AsyncCostManagementAPI
        from .namespaces.costs import AsyncCostsAPI
        from .namespaces.critiques import AsyncCritiquesAPI
        from .namespaces.crm import AsyncCRMAPI
        from .namespaces.cross_pollination import AsyncCrossPollinationAPI
        from .namespaces.dag_operations import AsyncDAGOperationsAPI
        from .namespaces.dashboard import AsyncDashboardAPI
        from .namespaces.debates import AsyncDebatesAPI
        from .namespaces.decisions import AsyncDecisionsAPI
        from .namespaces.deliberations import AsyncDeliberationsAPI
        from .namespaces.dependency_analysis import AsyncDependencyAnalysisAPI
        from .namespaces.devices import AsyncDevicesAPI
        from .namespaces.devops import AsyncDevopsAPI
        from .namespaces.disaster_recovery import AsyncDisasterRecoveryAPI
        from .namespaces.documents import AsyncDocumentsAPI
        from .namespaces.ecommerce import AsyncEcommerceAPI
        from .namespaces.email_debate import AsyncEmailDebateAPI
        from .namespaces.email_priority import AsyncEmailPriorityAPI
        from .namespaces.email_services import AsyncEmailServicesAPI
        from .namespaces.evaluation import AsyncEvaluationAPI
        from .namespaces.evolution import AsyncEvolutionAPI
        from .namespaces.expenses import AsyncExpensesAPI
        from .namespaces.explainability import AsyncExplainabilityAPI
        from .namespaces.external_agents import AsyncExternalAgentsAPI
        from .namespaces.facts import AsyncFactsAPI
        from .namespaces.features import AsyncFeaturesAPI
        from .namespaces.feedback import AsyncFeedbackAPI
        from .namespaces.flips import AsyncFlipsAPI
        from .namespaces.gateway import AsyncGatewayAPI
        from .namespaces.gauntlet import AsyncGauntletAPI
        from .namespaces.genesis import AsyncGenesisAPI
        from .namespaces.github import AsyncGithubAPI
        from .namespaces.gmail import AsyncGmailAPI
        from .namespaces.graph_debates import AsyncGraphDebatesAPI
        from .namespaces.health import AsyncHealthAPI
        from .namespaces.history import AsyncHistoryAPI
        from .namespaces.hybrid_debates import AsyncHybridDebatesAPI
        from .namespaces.ideas import AsyncIdeasAPI
        from .namespaces.inbox_command import AsyncInboxCommandAPI
        from .namespaces.index import AsyncIndexAPI
        from .namespaces.insights import AsyncInsightsAPI
        from .namespaces.integrations import AsyncIntegrationsAPI
        from .namespaces.introspection import AsyncIntrospectionAPI
        from .namespaces.invoice_processing import AsyncInvoiceProcessingAPI
        from .namespaces.knowledge import AsyncKnowledgeAPI
        from .namespaces.knowledge_chat import AsyncKnowledgeChatAPI
        from .namespaces.laboratory import AsyncLaboratoryAPI
        from .namespaces.leaderboard import AsyncLeaderboardAPI
        from .namespaces.learning import AsyncLearningAPI
        from .namespaces.marketplace import AsyncMarketplaceAPI
        from .namespaces.matches import AsyncMatchesAPI
        from .namespaces.matrix_debates import AsyncMatrixDebatesAPI
        from .namespaces.mcp import AsyncMCPAPI
        from .namespaces.media import AsyncMediaAPI
        from .namespaces.memory import AsyncMemoryAPI
        from .namespaces.metrics import AsyncMetricsAPI
        from .namespaces.ml import AsyncMLAPI
        from .namespaces.moderation import AsyncModerationAPI
        from .namespaces.modes import AsyncModesAPI
        from .namespaces.moments import AsyncMomentsAPI
        from .namespaces.monitoring import AsyncMonitoringAPI
        from .namespaces.nomic import AsyncNomicAPI
        from .namespaces.notifications import AsyncNotificationsAPI
        from .namespaces.oauth import AsyncOAuthAPI
        from .namespaces.oauth_wizard import AsyncOAuthWizardAPI
        from .namespaces.onboarding import AsyncOnboardingAPI
        from .namespaces.openapi import AsyncOpenApiAPI
        from .namespaces.openclaw import AsyncOpenclawAPI
        from .namespaces.orchestration import AsyncOrchestrationAPI
        from .namespaces.orchestration_canvas import AsyncOrchestrationCanvasAPI
        from .namespaces.organizations import AsyncOrganizationsAPI
        from .namespaces.outlook import AsyncOutlookAPI
        from .namespaces.partner import AsyncPartnerAPI
        from .namespaces.payments import AsyncPaymentsAPI
        from .namespaces.persona import AsyncPersonaAPI
        from .namespaces.pipeline import AsyncPipelineAPI
        from .namespaces.pipeline_transitions import AsyncPipelineTransitionsAPI
        from .namespaces.playground import AsyncPlaygroundAPI
        from .namespaces.plugins import AsyncPluginsAPI
        from .namespaces.podcast import AsyncPodcastAPI
        from .namespaces.policies import AsyncPoliciesAPI
        from .namespaces.privacy import AsyncPrivacyAPI
        from .namespaces.probes import AsyncProbesAPI
        from .namespaces.prompt_engine import AsyncPromptEngineAPI
        from .namespaces.pulse import AsyncPulseAPI
        from .namespaces.queue import AsyncQueueAPI
        from .namespaces.quotas import AsyncQuotasAPI
        from .namespaces.ranking import AsyncRankingAPI
        from .namespaces.rbac import AsyncRBACAPI
        from .namespaces.receipts import AsyncReceiptsAPI
        from .namespaces.reconciliation import AsyncReconciliationAPI
        from .namespaces.relationships import AsyncRelationshipsAPI
        from .namespaces.replays import AsyncReplaysAPI
        from .namespaces.repository import AsyncRepositoryAPI
        from .namespaces.reputation import AsyncReputationAPI
        from .namespaces.retention import AsyncRetentionAPI
        from .namespaces.review_queue import AsyncReviewQueueAPI
        from .namespaces.reviews import AsyncReviewsAPI
        from .namespaces.rlm import AsyncRLMAPI
        from .namespaces.routing import AsyncRoutingAPI
        from .namespaces.scim import AsyncSCIMAPI
        from .namespaces.search import AsyncSearchAPI
        from .namespaces.security import AsyncSecurityAPI
        from .namespaces.selection import AsyncSelectionAPI
        from .namespaces.self_improve import AsyncSelfImproveAPI
        from .namespaces.services import AsyncServicesAPI
        from .namespaces.settlements import AsyncSettlementAPI
        from .namespaces.shared_inbox import AsyncSharedInboxAPI
        from .namespaces.skills import AsyncSkillsAPI
        from .namespaces.slo import AsyncSLOAPI
        from .namespaces.sme import AsyncSMEAPI
        from .namespaces.social import AsyncSocialAPI
        from .namespaces.spectate import AsyncSpectateAPI
        from .namespaces.sso import AsyncSSOAPI
        from .namespaces.status import AsyncStatusAPI
        from .namespaces.support import AsyncSupportAPI
        from .namespaces.system import AsyncSystemAPI
        from .namespaces.teams import AsyncTeamsAPI
        from .namespaces.tenants import AsyncTenantsAPI
        from .namespaces.threat_intel import AsyncThreatIntelAPI
        from .namespaces.tournaments import AsyncTournamentsAPI
        from .namespaces.training import AsyncTrainingAPI
        from .namespaces.transcription import AsyncTranscriptionAPI
        from .namespaces.uncertainty import AsyncUncertaintyAPI
        from .namespaces.unified_inbox import AsyncUnifiedInboxAPI
        from .namespaces.usage import AsyncUsageAPI
        from .namespaces.usage_metering import AsyncUsageMeteringAPI
        from .namespaces.verification import AsyncVerificationAPI
        from .namespaces.verticals import AsyncVerticalsAPI
        from .namespaces.voice import AsyncVoiceAPI
        from .namespaces.webhooks import AsyncWebhooksAPI
        from .namespaces.workflow_templates import AsyncWorkflowTemplatesAPI
        from .namespaces.workflows import AsyncWorkflowsAPI
        from .namespaces.workspace_settings import AsyncWorkspaceSettingsAPI
        from .namespaces.workspaces import AsyncWorkspacesAPI
        from .namespaces.youtube import AsyncYouTubeAPI

        self.a2a = AsyncA2AAPI(self)
        self.accounting = AsyncAccountingAPI(self)
        self.actions = AsyncActionsAPI(self)
        self.admin = AsyncAdminAPI(self)
        self.agent_bridge = AsyncAgentBridgeAPI(self)
        self.advertising = AsyncAdvertisingAPI(self)
        self.agent_dashboard = AsyncAgentDashboardAPI(self)
        self.agent_selection = AsyncAgentSelectionAPI(self)
        self.agents = AsyncAgentsAPI(self)
        self.analytics = AsyncAnalyticsAPI(self)
        self.ap_automation = AsyncAPAutomationAPI(self)
        self.approvals = AsyncApprovalsAPI(self)
        self.ar_automation = AsyncARAutomationAPI(self)
        self.audience = AsyncAudienceAPI(self)
        self.audio = AsyncAudioAPI(self)
        self.audit = AsyncAuditAPI(self)
        self.audit_trail = AsyncAuditTrailAPI(self)
        self.auditing = AsyncAuditingAPI(self)
        self.auth = AsyncAuthAPI(self)
        self.autonomous = AsyncAutonomousAPI(self)
        self.backups = AsyncBackupsAPI(self)
        self.batch = AsyncBatchAPI(self)
        self.belief = AsyncBeliefAPI(self)
        self.belief_network = AsyncBeliefNetworkAPI(self)
        self.bots = AsyncBotsAPI(self)
        self.billing = AsyncBillingAPI(self)
        self.budgets = AsyncBudgetsAPI(self)
        self.blockchain = AsyncBlockchainAPI(self)
        self.calibration = AsyncCalibrationAPI(self)
        self.canvas = AsyncCanvasAPI(self)
        self.chat = AsyncChatAPI(self)
        self.dag_operations = AsyncDAGOperationsAPI(self)
        self.pipeline = AsyncPipelineAPI(self)
        self.pipeline_transitions = AsyncPipelineTransitionsAPI(self)
        self.playground = AsyncPlaygroundAPI(self)
        self.checkpoints = AsyncCheckpointsAPI(self)
        self.classify = AsyncClassifyAPI(self)
        self.code_review = AsyncCodeReviewAPI(self)
        self.codebase = AsyncCodebaseAPI(self)
        self.compliance = AsyncComplianceAPI(self)
        self.computer_use = AsyncComputerUseAPI(self)
        self.connectors = AsyncConnectorsAPI(self)
        self.consensus = AsyncConsensusAPI(self)
        self.control_plane = AsyncControlPlaneAPI(self)
        self.coordination = AsyncCoordinationAPI(self)
        self.cost_management = AsyncCostManagementAPI(self)
        self.costs = AsyncCostsAPI(self)
        self.critiques = AsyncCritiquesAPI(self)
        self.crm = AsyncCRMAPI(self)
        self.cross_pollination = AsyncCrossPollinationAPI(self)
        self.dashboard = AsyncDashboardAPI(self)
        self.debates = AsyncDebatesAPI(self)
        self.decisions = AsyncDecisionsAPI(self)
        self.deliberations = AsyncDeliberationsAPI(self)
        self.dependency_analysis = AsyncDependencyAnalysisAPI(self)
        self.devops = AsyncDevopsAPI(self)
        self.devices = AsyncDevicesAPI(self)
        self.disaster_recovery = AsyncDisasterRecoveryAPI(self)
        self.documents = AsyncDocumentsAPI(self)
        self.ecommerce = AsyncEcommerceAPI(self)
        self.email_debate = AsyncEmailDebateAPI(self)
        self.email_priority = AsyncEmailPriorityAPI(self)
        self.email_services = AsyncEmailServicesAPI(self)
        self.evaluation = AsyncEvaluationAPI(self)
        self.evolution = AsyncEvolutionAPI(self)
        self.expenses = AsyncExpensesAPI(self)
        self.explainability = AsyncExplainabilityAPI(self)
        self.external_agents = AsyncExternalAgentsAPI(self)
        self.facts = AsyncFactsAPI(self)
        self.features = AsyncFeaturesAPI(self)
        self.feedback = AsyncFeedbackAPI(self)
        self.flips = AsyncFlipsAPI(self)
        self.gateway = AsyncGatewayAPI(self)
        self.gauntlet = AsyncGauntletAPI(self)
        self.genesis = AsyncGenesisAPI(self)
        self.github = AsyncGithubAPI(self)
        self.gmail = AsyncGmailAPI(self)
        self.graph_debates = AsyncGraphDebatesAPI(self)
        self.health = AsyncHealthAPI(self)
        self.history = AsyncHistoryAPI(self)
        self.hybrid_debates = AsyncHybridDebatesAPI(self)
        self.inbox_command = AsyncInboxCommandAPI(self)
        self.ideas = AsyncIdeasAPI(self)
        self.index = AsyncIndexAPI(self)
        self.integrations = AsyncIntegrationsAPI(self)
        self.insights = AsyncInsightsAPI(self)
        self.introspection = AsyncIntrospectionAPI(self)
        self.invoice_processing = AsyncInvoiceProcessingAPI(self)
        self.knowledge = AsyncKnowledgeAPI(self)
        self.knowledge_chat = AsyncKnowledgeChatAPI(self)
        self.laboratory = AsyncLaboratoryAPI(self)
        self.leaderboard = AsyncLeaderboardAPI(self)
        self.learning = AsyncLearningAPI(self)
        self.marketplace = AsyncMarketplaceAPI(self)
        self.memory = AsyncMemoryAPI(self)
        self.matches = AsyncMatchesAPI(self)
        self.mcp = AsyncMCPAPI(self)
        self.matrix_debates = AsyncMatrixDebatesAPI(self)
        self.media = AsyncMediaAPI(self)
        self.metrics = AsyncMetricsAPI(self)
        self.ml = AsyncMLAPI(self)
        self.moderation = AsyncModerationAPI(self)
        self.modes = AsyncModesAPI(self)
        self.moments = AsyncMomentsAPI(self)
        self.monitoring = AsyncMonitoringAPI(self)
        self.nomic = AsyncNomicAPI(self)
        self.notifications = AsyncNotificationsAPI(self)
        self.oauth = AsyncOAuthAPI(self)
        self.oauth_wizard = AsyncOAuthWizardAPI(self)
        self.openclaw = AsyncOpenclawAPI(self)
        self.openapi = AsyncOpenApiAPI(self)
        self.orchestration = AsyncOrchestrationAPI(self)
        self.orchestration_canvas = AsyncOrchestrationCanvasAPI(self)
        self.onboarding = AsyncOnboardingAPI(self)
        self.organizations = AsyncOrganizationsAPI(self)
        self.outlook = AsyncOutlookAPI(self)
        self.partner = AsyncPartnerAPI(self)
        self.payments = AsyncPaymentsAPI(self)
        self.persona = AsyncPersonaAPI(self)
        self.plugins = AsyncPluginsAPI(self)
        self.podcast = AsyncPodcastAPI(self)
        self.policies = AsyncPoliciesAPI(self)
        self.privacy = AsyncPrivacyAPI(self)
        self.prompt_engine = AsyncPromptEngineAPI(self)
        self.probes = AsyncProbesAPI(self)
        self.pulse = AsyncPulseAPI(self)
        self.queue = AsyncQueueAPI(self)
        self.quotas = AsyncQuotasAPI(self)
        self.reconciliation = AsyncReconciliationAPI(self)
        self.ranking = AsyncRankingAPI(self)
        self.rbac = AsyncRBACAPI(self)
        self.receipts = AsyncReceiptsAPI(self)
        self.reputation = AsyncReputationAPI(self)
        self.retention = AsyncRetentionAPI(self)
        self.reviews = AsyncReviewsAPI(self)
        self.relationships = AsyncRelationshipsAPI(self)
        self.replays = AsyncReplaysAPI(self)
        self.review_queue = AsyncReviewQueueAPI(self)
        self.repository = AsyncRepositoryAPI(self)
        self.rlm = AsyncRLMAPI(self)
        self.routing = AsyncRoutingAPI(self)
        self.scim = AsyncSCIMAPI(self)
        self.search = AsyncSearchAPI(self)
        self.security = AsyncSecurityAPI(self)
        self.settlements = AsyncSettlementAPI(self)
        self.selection = AsyncSelectionAPI(self)
        self.self_improve = AsyncSelfImproveAPI(self)
        self.services = AsyncServicesAPI(self)
        self.shared_inbox = AsyncSharedInboxAPI(self)
        self.skills = AsyncSkillsAPI(self)
        self.slo = AsyncSLOAPI(self)
        self.sme = AsyncSMEAPI(self)
        self.social = AsyncSocialAPI(self)
        self.spectate = AsyncSpectateAPI(self)
        self.status = AsyncStatusAPI(self)
        self.sso = AsyncSSOAPI(self)
        self.support = AsyncSupportAPI(self)
        self.system = AsyncSystemAPI(self)
        self.teams = AsyncTeamsAPI(self)
        self.tenants = AsyncTenantsAPI(self)
        self.training = AsyncTrainingAPI(self)
        self.transcription = AsyncTranscriptionAPI(self)
        self.threat_intel = AsyncThreatIntelAPI(self)
        self.tournaments = AsyncTournamentsAPI(self)
        self.uncertainty = AsyncUncertaintyAPI(self)
        self.unified_inbox = AsyncUnifiedInboxAPI(self)
        self.usage = AsyncUsageAPI(self)
        self.usage_metering = AsyncUsageMeteringAPI(self)
        self.verification = AsyncVerificationAPI(self)
        self.verticals = AsyncVerticalsAPI(self)
        self.voice = AsyncVoiceAPI(self)
        self.webhooks = AsyncWebhooksAPI(self)
        self.workflow_templates = AsyncWorkflowTemplatesAPI(self)
        self.workflows = AsyncWorkflowsAPI(self)
        self.workspace_settings = AsyncWorkspaceSettingsAPI(self)
        self.workspaces = AsyncWorkspacesAPI(self)
        self.youtube = AsyncYouTubeAPI(self)

    @overload
    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        *,
        response_format: Literal["json"] = "json",
    ) -> dict[str, Any]: ...

    @overload
    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        *,
        response_format: Literal["text"],
    ) -> str: ...

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        *,
        response_format: Literal["json", "text"] = "json",
    ) -> dict[str, Any] | str:
        """
        Make an async HTTP request to the Aragora API.

        In demo mode, returns mock data without making network calls.

        Args:
            method: HTTP method
            path: API path
            params: Query parameters
            json: JSON body
            headers: Additional headers
            response_format: Parse the response as JSON or return its text body

        Returns:
            Parsed JSON response as a dictionary.
        """
        if self.demo:
            from .demo import demo_request

            result = demo_request(method, path, params=params, json=json, headers=headers)
            if response_format == "text":
                if isinstance(result, str):
                    return result
                # Mirror the live API: a deployment without this text resource
                # (e.g. no ODR signing key in demo mode) answers 404.
                raise NotFoundError(f"Demo mode has no text response for '{path}'")
            return result

        import asyncio

        url = urljoin(self.base_url, path)
        request_headers = {**self._build_headers(), **(headers or {})}

        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = await self._client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json,
                    headers=request_headers,
                )

                if response.is_success:
                    if response_format == "text":
                        return response.text
                    if response.content:
                        return cast(dict[str, Any], response.json())
                    return {}

                self._handle_error_response(response)

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                    continue
                raise AragoraError("Request timed out") from e

            except httpx.ConnectError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                    continue
                raise AragoraError("Connection failed") from e

            except RateLimitError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    # Use server-specified retry delay if available
                    delay = (
                        e.retry_after
                        if e.retry_after is not None
                        else self.retry_delay * (2**attempt)
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        if last_error:
            raise AragoraError(f"Request failed after {self.max_retries} retries") from last_error

        raise AragoraError("Unexpected error")

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Backward-compatible alias for request()."""
        return await self.request(method, path, params=params, json=json, headers=headers)

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Handle error responses."""
        try:
            body = response.json()
            message = body.get("error", body.get("message", response.text))
            error_code = body.get("code")
            trace_id = body.get("trace_id")
        except (ValueError, AttributeError):
            body = None
            message = response.text or "Unknown error"
            error_code = None
            trace_id = None

        status = response.status_code

        if status == 401:
            raise AuthenticationError(
                message, error_code=error_code, trace_id=trace_id, response_body=body
            )
        elif status == 403:
            raise AuthorizationError(
                message, error_code=error_code, trace_id=trace_id, response_body=body
            )
        elif status == 404:
            raise NotFoundError(
                message, error_code=error_code, trace_id=trace_id, response_body=body
            )
        elif status == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitError(
                message,
                retry_after=_parse_retry_after(retry_after),
                error_code=error_code,
                trace_id=trace_id,
                response_body=body,
            )
        elif status == 400:
            errors = body.get("errors") if body else None
            raise ValidationError(
                message,
                errors=errors,
                error_code=error_code,
                trace_id=trace_id,
                response_body=body,
            )
        elif status >= 500:
            raise ServerError(
                message,
                status_code=status,
                error_code=error_code,
                trace_id=trace_id,
                response_body=body,
            )
        else:
            raise AragoraError(
                message,
                status_code=status,
                error_code=error_code,
                trace_id=trace_id,
                response_body=body,
            )

    @property
    def stream(self) -> AragoraWebSocket:
        """Lazy-initialized WebSocket client for real-time event streaming."""
        if self._stream is None:
            from .websocket import AragoraWebSocket

            self._stream = AragoraWebSocket(
                base_url=self.base_url,
                api_key=self.api_key,
                ws_url=self.ws_url,
            )
        return self._stream

    async def close(self) -> None:
        """Close the HTTP client and any open WebSocket connection."""
        if self._stream is not None:
            await self._stream.close()
            self._stream = None
        if self._client is not None:
            await self._client.aclose()

    async def __aenter__(self) -> AragoraAsyncClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

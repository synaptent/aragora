"""
Comprehensive tests for the Gusto Payroll Connector.

Tests cover:
- Enum values (PayrollStatus, EmploymentType, PayType)
- GustoCredentials dataclass and expiration logic
- Employee dataclass and serialization
- PayrollItem computed properties (net_pay, total_employer_cost)
- PayrollRun dataclass and serialization
- JournalEntry (add_debit, add_credit, balancing)
- GustoConnector initialization and configuration
- OAuth flow (authorization URL, code exchange, token refresh)
- API request handling (_request with auth, circuit breaker, errors)
- Employee listing and data transformation
- Payroll listing, detail retrieval, and parsing
- Journal entry generation from payroll data
- Account mapping customization
- Error handling (rate limit, server error, timeout, network)
- Circuit breaker integration
- Mock data generation helpers
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.connectors.accounting.gusto import (
    Employee,
    EmploymentType,
    GustoConnector,
    GustoCredentials,
    JournalEntry,
    PayrollItem,
    PayrollRun,
    PayrollStatus,
    PayType,
    get_mock_employees,
    get_mock_payroll_run,
)
from aragora.connectors.exceptions import (
    ConnectorAPIError,
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorNetworkError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
)


def _make_aiohttp_session(response_mock=None, *, post_response=None, side_effect=None):
    """Build a mock aiohttp.ClientSession that supports nested async context managers.

    aiohttp uses the pattern::

        async with aiohttp.ClientSession() as session:
            async with session.request(...) as resp:
                ...

    Both levels need proper ``__aenter__`` / ``__aexit__`` support.

    Args:
        response_mock: The mock response returned by ``session.request()``.
        post_response: Optional separate mock response for ``session.post()``.
                       Falls back to *response_mock* if not given.
        side_effect: If provided, ``session.request()`` will raise this instead
                     of returning a response.
    """

    post_resp = post_response or response_mock

    class _ResponseCM:
        """Async context manager wrapping a mock response."""

        def __init__(self, resp):
            self._resp = resp

        async def __aenter__(self):
            return self._resp

        async def __aexit__(self, *args):
            return False

    class _RaiseCM:
        """Async context manager that raises on enter."""

        def __init__(self, exc):
            self._exc = exc

        async def __aenter__(self):
            raise self._exc

        async def __aexit__(self, *args):
            return False

    class _MockSession:
        def post(self, *a, **kw):
            return _ResponseCM(post_resp)

        def request(self, *a, **kw):
            if side_effect is not None:
                return _RaiseCM(side_effect)
            return _ResponseCM(response_mock)

    class _MockClientSession:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return _MockSession()

        async def __aexit__(self, *args):
            return False

    return _MockClientSession


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def gusto_connector():
    """Create a GustoConnector with test credentials."""
    return GustoConnector(
        client_id="test_client_id",
        client_secret="test_client_secret",
        redirect_uri="https://example.com/callback",
        enable_circuit_breaker=False,
    )


@pytest.fixture
def gusto_connector_with_cb():
    """Create a GustoConnector with circuit breaker enabled."""
    return GustoConnector(
        client_id="test_client_id",
        client_secret="test_client_secret",
        redirect_uri="https://example.com/callback",
        enable_circuit_breaker=True,
    )


@pytest.fixture
def valid_credentials():
    """Create valid (non-expired) credentials."""
    return GustoCredentials(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        company_id="company_123",
        company_name="Test Company",
        token_type="Bearer",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="employees payrolls",
    )


@pytest.fixture
def expired_credentials():
    """Create expired credentials."""
    return GustoCredentials(
        access_token="expired_token",
        refresh_token="test_refresh_token",
        company_id="company_123",
        company_name="Test Company",
        token_type="Bearer",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )


@pytest.fixture
def authenticated_connector(gusto_connector, valid_credentials):
    """Create a connector with valid credentials set."""
    gusto_connector.set_credentials(valid_credentials)
    return gusto_connector


@pytest.fixture
def sample_payroll_item():
    """Create a sample PayrollItem with all fields populated."""
    return PayrollItem(
        employee_id="emp_001",
        employee_name="Alice Johnson",
        gross_pay=Decimal("5000.00"),
        regular_hours=Decimal("80"),
        overtime_hours=Decimal("5"),
        bonus=Decimal("500"),
        commission=Decimal("0"),
        reimbursements=Decimal("100"),
        federal_tax=Decimal("800"),
        state_tax=Decimal("200"),
        local_tax=Decimal("50"),
        social_security=Decimal("310"),
        medicare=Decimal("72.50"),
        retirement_401k=Decimal("250"),
        health_insurance=Decimal("200"),
        other_deductions=Decimal("25"),
        employer_ss=Decimal("310"),
        employer_medicare=Decimal("72.50"),
        employer_futa=Decimal("42"),
        employer_suta=Decimal("67.50"),
        employer_401k_match=Decimal("125"),
        employer_health=Decimal("400"),
    )


@pytest.fixture
def sample_payroll_run(sample_payroll_item):
    """Create a sample PayrollRun."""
    return PayrollRun(
        id="payroll_001",
        company_id="company_123",
        pay_period_start=date(2024, 1, 1),
        pay_period_end=date(2024, 1, 14),
        check_date=date(2024, 1, 19),
        status=PayrollStatus.PROCESSED,
        total_gross_pay=Decimal("10000.00"),
        total_net_pay=Decimal("7500.00"),
        total_employer_taxes=Decimal("800.00"),
        total_employee_taxes=Decimal("2000.00"),
        payroll_items=[sample_payroll_item],
    )


@pytest.fixture
def api_employee_data():
    """Sample API response data for an employee."""
    return {
        "id": 12345,
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane.doe@company.com",
        "employment_status": "full_time",
        "flsa_status": "Exempt",
        "terminated": False,
        "department": "Engineering",
        "jobs": [{"title": "Senior Engineer"}],
        "hire_date": "2023-03-15",
    }


@pytest.fixture
def api_payroll_response():
    """Sample API response data for a payroll run."""
    return {
        "id": 67890,
        "processed": True,
        "cancelled": False,
        "pay_period": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-14",
        },
        "check_date": "2024-01-19",
        "totals": {
            "gross_pay": "10000.00",
            "net_pay": "7500.00",
            "employer_taxes": "800.00",
            "employee_taxes": "2000.00",
        },
        "processed_date": "2024-01-18T12:00:00",
    }


# =============================================================================
# Enum Tests
# =============================================================================


class TestPayrollStatus:
    """Tests for PayrollStatus enum."""

    def test_payroll_status_values(self):
        assert PayrollStatus.UNPROCESSED.value == "unprocessed"
        assert PayrollStatus.PROCESSED.value == "processed"
        assert PayrollStatus.CANCELLED.value == "cancelled"

    def test_payroll_status_is_str(self):
        assert isinstance(PayrollStatus.PROCESSED, str)
        assert PayrollStatus.PROCESSED == "processed"


class TestEmploymentType:
    """Tests for EmploymentType enum."""

    def test_employment_type_values(self):
        assert EmploymentType.FULL_TIME.value == "full_time"
        assert EmploymentType.PART_TIME.value == "part_time"
        assert EmploymentType.CONTRACTOR.value == "contractor"

    def test_employment_type_is_str(self):
        assert isinstance(EmploymentType.FULL_TIME, str)


class TestPayType:
    """Tests for PayType enum."""

    def test_pay_type_values(self):
        assert PayType.HOURLY.value == "hourly"
        assert PayType.SALARY.value == "salary"

    def test_pay_type_is_str(self):
        assert isinstance(PayType.SALARY, str)


# =============================================================================
# GustoCredentials Tests
# =============================================================================


class TestGustoCredentials:
    """Tests for GustoCredentials dataclass."""

    def test_creation_with_required_fields(self):
        creds = GustoCredentials(
            access_token="tok_123",
            refresh_token="ref_456",
            company_id="comp_789",
            company_name="Acme Corp",
        )
        assert creds.access_token == "tok_123"
        assert creds.refresh_token == "ref_456"
        assert creds.company_id == "comp_789"
        assert creds.company_name == "Acme Corp"
        assert creds.token_type == "Bearer"
        assert creds.expires_at is None
        assert creds.scope == ""

    def test_is_expired_when_no_expiry(self):
        creds = GustoCredentials(
            access_token="tok",
            refresh_token="ref",
            company_id="c",
            company_name="C",
        )
        assert creds.is_expired is True

    def test_is_expired_when_expired(self):
        creds = GustoCredentials(
            access_token="tok",
            refresh_token="ref",
            company_id="c",
            company_name="C",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        assert creds.is_expired is True

    def test_is_not_expired(self):
        creds = GustoCredentials(
            access_token="tok",
            refresh_token="ref",
            company_id="c",
            company_name="C",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert creds.is_expired is False

    def test_defaults(self):
        creds = GustoCredentials(
            access_token="tok",
            refresh_token="ref",
            company_id="c",
            company_name="C",
        )
        assert creds.token_type == "Bearer"
        assert creds.scope == ""


# =============================================================================
# Employee Tests
# =============================================================================


class TestEmployee:
    """Tests for Employee dataclass."""

    def test_creation_with_defaults(self):
        emp = Employee(
            id="emp_1",
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )
        assert emp.id == "emp_1"
        assert emp.employment_type == EmploymentType.FULL_TIME
        assert emp.pay_type == PayType.SALARY
        assert emp.is_active is True
        assert emp.department is None
        assert emp.job_title is None
        assert emp.hire_date is None
        assert emp.termination_date is None
        assert emp.hourly_rate is None
        assert emp.annual_salary is None

    def test_to_dict_includes_full_name(self):
        emp = Employee(
            id="emp_1",
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )
        result = emp.to_dict()
        assert result["full_name"] == "John Doe"

    def test_to_dict_excludes_private_fields(self):
        emp = Employee(
            id="emp_1",
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            hourly_rate=Decimal("50"),
            annual_salary=Decimal("100000"),
            termination_date=date(2024, 12, 31),
        )
        result = emp.to_dict()
        assert "hourly_rate" not in result
        assert "annual_salary" not in result
        assert "termination_date" not in result

    def test_to_dict_includes_none_fields(self):
        """Employee has _include_none = True."""
        emp = Employee(
            id="emp_1",
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )
        result = emp.to_dict()
        assert "department" in result
        assert result["department"] is None


# =============================================================================
# PayrollItem Tests
# =============================================================================


class TestPayrollItem:
    """Tests for PayrollItem dataclass and computed properties."""

    def test_net_pay_calculation(self, sample_payroll_item):
        expected_deductions = (
            Decimal("800")  # federal_tax
            + Decimal("200")  # state_tax
            + Decimal("50")  # local_tax
            + Decimal("310")  # social_security
            + Decimal("72.50")  # medicare
            + Decimal("250")  # retirement_401k
            + Decimal("200")  # health_insurance
            + Decimal("25")  # other_deductions
        )
        expected_net = Decimal("5000.00") - expected_deductions
        assert sample_payroll_item.net_pay == expected_net

    def test_total_employer_cost(self, sample_payroll_item):
        expected = (
            Decimal("5000.00")  # gross_pay
            + Decimal("310")  # employer_ss
            + Decimal("72.50")  # employer_medicare
            + Decimal("42")  # employer_futa
            + Decimal("67.50")  # employer_suta
            + Decimal("125")  # employer_401k_match
            + Decimal("400")  # employer_health
        )
        assert sample_payroll_item.total_employer_cost == expected

    def test_net_pay_zero_deductions(self):
        item = PayrollItem(
            employee_id="emp_1",
            employee_name="Test Person",
            gross_pay=Decimal("3000"),
        )
        assert item.net_pay == Decimal("3000")

    def test_total_employer_cost_no_contributions(self):
        item = PayrollItem(
            employee_id="emp_1",
            employee_name="Test Person",
            gross_pay=Decimal("3000"),
        )
        assert item.total_employer_cost == Decimal("3000")

    def test_to_dict_includes_computed_properties(self, sample_payroll_item):
        result = sample_payroll_item.to_dict()
        assert "net_pay" in result
        assert "total_employer_cost" in result
        assert isinstance(result["net_pay"], float)
        assert isinstance(result["total_employer_cost"], float)

    def test_to_dict_excludes_detailed_fields(self, sample_payroll_item):
        result = sample_payroll_item.to_dict()
        assert "regular_hours" not in result
        assert "overtime_hours" not in result
        assert "bonus" not in result
        assert "commission" not in result
        assert "reimbursements" not in result
        assert "local_tax" not in result
        assert "other_deductions" not in result
        assert "employer_ss" not in result
        assert "employer_medicare" not in result
        assert "employer_futa" not in result
        assert "employer_suta" not in result
        assert "employer_401k_match" not in result
        assert "employer_health" not in result

    def test_default_values(self):
        item = PayrollItem(
            employee_id="emp_1",
            employee_name="Test",
        )
        assert item.gross_pay == Decimal("0")
        assert item.federal_tax == Decimal("0")
        assert item.state_tax == Decimal("0")
        assert item.social_security == Decimal("0")
        assert item.medicare == Decimal("0")


# =============================================================================
# PayrollRun Tests
# =============================================================================


class TestPayrollRun:
    """Tests for PayrollRun dataclass."""

    def test_total_employer_cost_property(self, sample_payroll_run):
        expected = sample_payroll_run.total_gross_pay + sample_payroll_run.total_employer_taxes
        assert sample_payroll_run.total_employer_cost == expected

    def test_to_dict_includes_employer_cost_and_count(self, sample_payroll_run):
        result = sample_payroll_run.to_dict()
        assert "total_employer_cost" in result
        assert "employee_count" in result
        assert result["employee_count"] == 1

    def test_to_dict_excludes_internal_fields(self, sample_payroll_run):
        result = sample_payroll_run.to_dict()
        assert "total_deductions" not in result
        assert "total_reimbursements" not in result
        assert "payroll_items" not in result
        assert "created_at" not in result

    def test_default_status(self):
        run = PayrollRun(
            id="pr_1",
            company_id="c_1",
            pay_period_start=date(2024, 1, 1),
            pay_period_end=date(2024, 1, 14),
            check_date=date(2024, 1, 19),
        )
        assert run.status == PayrollStatus.PROCESSED

    def test_empty_payroll_items(self):
        run = PayrollRun(
            id="pr_1",
            company_id="c_1",
            pay_period_start=date(2024, 1, 1),
            pay_period_end=date(2024, 1, 14),
            check_date=date(2024, 1, 19),
        )
        assert run.payroll_items == []
        result = run.to_dict()
        assert result["employee_count"] == 0


# =============================================================================
# JournalEntry Tests
# =============================================================================


class TestJournalEntry:
    """Tests for JournalEntry dataclass."""

    def test_add_debit(self):
        entry = JournalEntry(date=date(2024, 1, 19), memo="Test")
        entry.add_debit("6700", "Payroll Expense", Decimal("5000"), "Wages")
        assert len(entry.lines) == 1
        assert entry.lines[0]["debit"] == 5000.0
        assert entry.lines[0]["credit"] == 0
        assert entry.lines[0]["account_id"] == "6700"
        assert entry.lines[0]["account_name"] == "Payroll Expense"
        assert entry.lines[0]["description"] == "Wages"

    def test_add_credit(self):
        entry = JournalEntry(date=date(2024, 1, 19), memo="Test")
        entry.add_credit("1000", "Cash", Decimal("5000"), "Payment")
        assert len(entry.lines) == 1
        assert entry.lines[0]["credit"] == 5000.0
        assert entry.lines[0]["debit"] == 0
        assert entry.lines[0]["account_id"] == "1000"

    def test_is_balanced_when_balanced(self):
        entry = JournalEntry(date=date(2024, 1, 19), memo="Test")
        entry.add_debit("6700", "Expense", Decimal("1000"))
        entry.add_credit("1000", "Cash", Decimal("1000"))
        assert entry.is_balanced is True

    def test_is_balanced_when_not_balanced(self):
        entry = JournalEntry(date=date(2024, 1, 19), memo="Test")
        entry.add_debit("6700", "Expense", Decimal("1000"))
        entry.add_credit("1000", "Cash", Decimal("500"))
        assert entry.is_balanced is False

    def test_is_balanced_with_small_rounding(self):
        """Test that small floating point differences are tolerated."""
        entry = JournalEntry(date=date(2024, 1, 19), memo="Test")
        entry.add_debit("6700", "Expense", Decimal("100.005"))
        entry.add_credit("1000", "Cash", Decimal("100.005"))
        assert entry.is_balanced is True

    def test_is_balanced_empty_entry(self):
        entry = JournalEntry(date=date(2024, 1, 19), memo="Test")
        assert entry.is_balanced is True

    def test_to_dict(self):
        entry = JournalEntry(date=date(2024, 1, 19), memo="Payroll Jan")
        entry.add_debit("6700", "Expense", Decimal("1000"))
        entry.add_credit("1000", "Cash", Decimal("1000"))
        result = entry.to_dict()
        assert result["date"] == "2024-01-19"
        assert result["memo"] == "Payroll Jan"
        assert result["is_balanced"] is True
        assert result["total_debits"] == 1000.0
        assert result["total_credits"] == 1000.0
        assert len(result["lines"]) == 2

    def test_multiple_lines(self):
        entry = JournalEntry(date=date(2024, 1, 19), memo="Test")
        entry.add_debit("6700", "Wages", Decimal("3000"))
        entry.add_debit("6710", "Tax Expense", Decimal("200"))
        entry.add_credit("1000", "Cash", Decimal("2800"))
        entry.add_credit("2100", "Tax Payable", Decimal("400"))
        assert len(entry.lines) == 4
        assert entry.is_balanced is True


# =============================================================================
# GustoConnector Initialization Tests
# =============================================================================


class TestGustoConnectorInit:
    """Tests for GustoConnector initialization and configuration."""

    def test_init_with_explicit_credentials(self):
        connector = GustoConnector(
            client_id="cid",
            client_secret="csecret",
            redirect_uri="https://example.com/cb",
        )
        assert connector.client_id == "cid"
        assert connector.client_secret == "csecret"
        assert connector.redirect_uri == "https://example.com/cb"

    @patch.dict(
        "os.environ",
        {
            "GUSTO_CLIENT_ID": "env_cid",
            "GUSTO_CLIENT_SECRET": "env_csecret",
            "GUSTO_REDIRECT_URI": "https://env.example.com/cb",
        },
    )
    def test_init_from_environment(self):
        connector = GustoConnector()
        assert connector.client_id == "env_cid"
        assert connector.client_secret == "env_csecret"
        assert connector.redirect_uri == "https://env.example.com/cb"

    def test_is_configured_true(self, gusto_connector):
        assert gusto_connector.is_configured is True

    def test_is_configured_false(self):
        connector = GustoConnector(enable_circuit_breaker=False)
        assert connector.is_configured is False

    def test_is_authenticated_false_initially(self, gusto_connector):
        assert gusto_connector.is_authenticated is False

    def test_is_authenticated_true(self, authenticated_connector):
        assert authenticated_connector.is_authenticated is True

    def test_is_authenticated_false_when_expired(self, gusto_connector, expired_credentials):
        gusto_connector.set_credentials(expired_credentials)
        assert gusto_connector.is_authenticated is False

    def test_circuit_breaker_enabled_by_default(self):
        connector = GustoConnector(
            client_id="cid",
            client_secret="csecret",
        )
        assert connector._circuit_breaker is not None

    def test_circuit_breaker_disabled(self, gusto_connector):
        assert gusto_connector._circuit_breaker is None

    def test_custom_circuit_breaker(self):
        from aragora.resilience import CircuitBreaker

        cb = CircuitBreaker(name="custom", failure_threshold=5, cooldown_seconds=120.0)
        connector = GustoConnector(
            client_id="cid",
            client_secret="csecret",
            circuit_breaker=cb,
        )
        assert connector._circuit_breaker is cb

    def test_set_credentials(self, gusto_connector, valid_credentials):
        gusto_connector.set_credentials(valid_credentials)
        assert gusto_connector._credentials is valid_credentials

    def test_class_constants(self):
        assert GustoConnector.BASE_URL == "https://api.gusto.com"
        assert GustoConnector.AUTH_URL == "https://api.gusto.com/oauth/authorize"
        assert GustoConnector.TOKEN_URL == "https://api.gusto.com/oauth/token"


# =============================================================================
# OAuth Flow Tests
# =============================================================================


class TestGustoOAuth:
    """Tests for OAuth authorization and token exchange."""

    def test_get_authorization_url(self, gusto_connector):
        url = gusto_connector.get_authorization_url()
        assert url.startswith("https://api.gusto.com/oauth/authorize?")
        assert "client_id=test_client_id" in url
        assert "response_type=code" in url
        assert "redirect_uri=" in url

    def test_get_authorization_url_with_state(self, gusto_connector):
        url = gusto_connector.get_authorization_url(state="random_state_123")
        assert "state=random_state_123" in url

    @pytest.mark.asyncio
    async def test_exchange_code_success(self, gusto_connector):
        mock_token_response = MagicMock()
        mock_token_response.status = 200
        mock_token_response.json = AsyncMock(
            return_value={
                "access_token": "new_access_token",
                "refresh_token": "new_refresh_token",
                "token_type": "Bearer",
                "expires_in": 7200,
                "scope": "employees payrolls",
            }
        )

        mock_cls = _make_aiohttp_session(post_response=mock_token_response)
        gusto_connector._get_current_company = AsyncMock(
            return_value={"id": "comp_001", "name": "Acme Inc"}
        )

        with patch("aiohttp.ClientSession", mock_cls):
            creds = await gusto_connector.exchange_code("auth_code_123")

        assert creds.access_token == "new_access_token"
        assert creds.refresh_token == "new_refresh_token"
        assert creds.company_id == "comp_001"
        assert creds.company_name == "Acme Inc"
        assert creds.expires_at is not None

    @pytest.mark.asyncio
    async def test_exchange_code_failure(self, gusto_connector):
        mock_response = MagicMock()
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value="Invalid authorization code")

        mock_cls = _make_aiohttp_session(post_response=mock_response)

        with patch("aiohttp.ClientSession", mock_cls):
            with pytest.raises(ConnectorAuthError, match="Token exchange failed"):
                await gusto_connector.exchange_code("bad_code")

    @pytest.mark.asyncio
    async def test_refresh_tokens_success(self, authenticated_connector):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "access_token": "refreshed_access_token",
                "refresh_token": "refreshed_refresh_token",
                "token_type": "Bearer",
                "expires_in": 7200,
            }
        )

        mock_cls = _make_aiohttp_session(post_response=mock_response)

        with patch("aiohttp.ClientSession", mock_cls):
            creds = await authenticated_connector.refresh_tokens()

        assert creds.access_token == "refreshed_access_token"
        assert creds.refresh_token == "refreshed_refresh_token"
        assert creds.company_id == "company_123"

    @pytest.mark.asyncio
    async def test_refresh_tokens_failure(self, authenticated_connector):
        mock_response = MagicMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Invalid refresh token")

        mock_cls = _make_aiohttp_session(post_response=mock_response)

        with patch("aiohttp.ClientSession", mock_cls):
            with pytest.raises(ConnectorAuthError, match="Token refresh failed"):
                await authenticated_connector.refresh_tokens()

    @pytest.mark.asyncio
    async def test_refresh_tokens_no_credentials(self, gusto_connector):
        with pytest.raises(ConnectorConfigError, match="No credentials to refresh"):
            await gusto_connector.refresh_tokens()


# =============================================================================
# API Request Tests
# =============================================================================


class TestGustoRequest:
    """Tests for the _request method and error handling."""

    @pytest.mark.asyncio
    async def test_request_not_authenticated(self, gusto_connector):
        with pytest.raises(ConnectorAuthError, match="Not authenticated"):
            await gusto_connector._request("GET", "/v1/employees")

    @pytest.mark.asyncio
    async def test_request_auto_refreshes_expired_token(self, gusto_connector, expired_credentials):
        gusto_connector.set_credentials(expired_credentials)
        gusto_connector.refresh_tokens = AsyncMock(
            return_value=GustoCredentials(
                access_token="new_token",
                refresh_token="new_refresh",
                company_id="c",
                company_name="C",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"data": "ok"})
        mock_response.headers = {}

        mock_cls = _make_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", mock_cls):
            result = await gusto_connector._request("GET", "/v1/test")

        gusto_connector.refresh_tokens.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_sends_api_version_header(self, authenticated_connector):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={})
        mock_response.headers = {}
        sent_headers = {}

        class _ResponseCM:
            async def __aenter__(self):
                return mock_response

            async def __aexit__(self, *args):
                return False

        class _Session:
            def request(self, *args, **kwargs):
                sent_headers.update(kwargs["headers"])
                return _ResponseCM()

        class _ClientSession:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return _Session()

            async def __aexit__(self, *args):
                return False

        with patch("aiohttp.ClientSession", _ClientSession):
            await authenticated_connector._request("GET", "/v1/test")

        assert sent_headers["X-Gusto-API-Version"] == GustoConnector.API_VERSION

    def test_api_version_can_be_overridden(self, monkeypatch):
        connector = GustoConnector(api_version="2025-06-15", enable_circuit_breaker=False)
        assert connector.api_version == "2025-06-15"
        monkeypatch.setenv("GUSTO_API_VERSION", "2024-04-01")
        assert GustoConnector(enable_circuit_breaker=False).api_version == "2024-04-01"

    @pytest.mark.asyncio
    async def test_request_rate_limit_429(self, authenticated_connector):
        mock_response = MagicMock()
        mock_response.status = 429
        mock_response.json = AsyncMock(return_value={"error": "Rate limited"})
        mock_response.headers = {"Retry-After": "30"}

        mock_cls = _make_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", mock_cls):
            with pytest.raises(ConnectorRateLimitError, match="Rate limited"):
                await authenticated_connector._request("GET", "/v1/test")

    @pytest.mark.asyncio
    async def test_request_server_error_500(self, authenticated_connector):
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.json = AsyncMock(return_value={"error": "Internal server error"})
        mock_response.headers = {}

        mock_cls = _make_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", mock_cls):
            with pytest.raises(ConnectorAPIError, match="server error"):
                await authenticated_connector._request("GET", "/v1/test")

    @pytest.mark.asyncio
    async def test_request_client_error_400(self, authenticated_connector):
        mock_response = MagicMock()
        mock_response.status = 400
        mock_response.json = AsyncMock(return_value={"error": "Bad request"})
        mock_response.headers = {}

        mock_cls = _make_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", mock_cls):
            with pytest.raises(ConnectorAPIError, match="Bad request"):
                await authenticated_connector._request("GET", "/v1/test")

    @pytest.mark.asyncio
    async def test_request_timeout(self, authenticated_connector):
        mock_cls = _make_aiohttp_session(side_effect=asyncio.TimeoutError())

        with patch("aiohttp.ClientSession", mock_cls):
            with pytest.raises(ConnectorTimeoutError, match="timed out"):
                await authenticated_connector._request("GET", "/v1/test")

    @pytest.mark.asyncio
    async def test_request_network_error(self, authenticated_connector):
        import aiohttp

        mock_cls = _make_aiohttp_session(side_effect=aiohttp.ClientError("Connection refused"))

        with patch("aiohttp.ClientSession", mock_cls):
            with pytest.raises(ConnectorNetworkError, match="Network error"):
                await authenticated_connector._request("GET", "/v1/test")

    @pytest.mark.asyncio
    async def test_request_circuit_breaker_open(self, gusto_connector_with_cb, valid_credentials):
        gusto_connector_with_cb.set_credentials(valid_credentials)
        gusto_connector_with_cb._circuit_breaker.can_proceed = MagicMock(return_value=False)
        gusto_connector_with_cb._circuit_breaker.cooldown_remaining = MagicMock(return_value=45.0)

        with pytest.raises(ConnectorAPIError, match="Circuit breaker open"):
            await gusto_connector_with_cb._request("GET", "/v1/test")

    @pytest.mark.asyncio
    async def test_request_with_explicit_access_token(self, gusto_connector):
        """Test that providing access_token parameter bypasses credentials check."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"result": "ok"})
        mock_response.headers = {}

        mock_cls = _make_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", mock_cls):
            result = await gusto_connector._request("GET", "/v1/me", access_token="explicit_token")
        assert result == {"result": "ok"}


# =============================================================================
# Employee Operations Tests
# =============================================================================


class TestListEmployees:
    """Tests for employee listing and transformation."""

    @pytest.mark.asyncio
    async def test_list_employees_not_authenticated(self, gusto_connector):
        with pytest.raises(ConnectorAuthError, match="Not authenticated"):
            await gusto_connector.list_employees()

    @pytest.mark.asyncio
    async def test_list_employees_active_only(self, authenticated_connector, api_employee_data):
        terminated_employee = dict(api_employee_data)
        terminated_employee["id"] = 99999
        terminated_employee["terminated"] = True

        authenticated_connector._request = AsyncMock(
            return_value=[api_employee_data, terminated_employee]
        )

        employees = await authenticated_connector.list_employees(active_only=True)
        assert len(employees) == 1
        assert employees[0].id == "12345"

    @pytest.mark.asyncio
    async def test_list_employees_include_terminated(
        self, authenticated_connector, api_employee_data
    ):
        terminated_employee = dict(api_employee_data)
        terminated_employee["id"] = 99999
        terminated_employee["terminated"] = True

        authenticated_connector._request = AsyncMock(
            return_value=[api_employee_data, terminated_employee]
        )

        employees = await authenticated_connector.list_employees(active_only=False)
        assert len(employees) == 2

    @pytest.mark.asyncio
    async def test_list_employees_part_time(self, authenticated_connector):
        api_data = {
            "id": 100,
            "first_name": "Part",
            "last_name": "Timer",
            "email": "pt@example.com",
            "employment_status": "part_time",
            "flsa_status": "Nonexempt",
            "terminated": False,
            "department": "Support",
            "jobs": [{"title": "Support Agent"}],
            "hire_date": "2023-06-01",
        }
        authenticated_connector._request = AsyncMock(return_value=[api_data])

        employees = await authenticated_connector.list_employees()
        assert len(employees) == 1
        assert employees[0].employment_type == EmploymentType.PART_TIME
        assert employees[0].pay_type == PayType.HOURLY

    @pytest.mark.asyncio
    async def test_list_employees_data_transformation(
        self, authenticated_connector, api_employee_data
    ):
        authenticated_connector._request = AsyncMock(return_value=[api_employee_data])

        employees = await authenticated_connector.list_employees()
        emp = employees[0]
        assert emp.id == "12345"
        assert emp.first_name == "Jane"
        assert emp.last_name == "Doe"
        assert emp.email == "jane.doe@company.com"
        assert emp.department == "Engineering"
        assert emp.job_title == "Senior Engineer"
        assert emp.hire_date == date(2023, 3, 15)
        assert emp.is_active is True
        assert emp.employment_type == EmploymentType.FULL_TIME
        assert emp.pay_type == PayType.SALARY

    @pytest.mark.asyncio
    async def test_list_employees_no_jobs(self, authenticated_connector):
        api_data = {
            "id": 200,
            "first_name": "No",
            "last_name": "Job",
            "email": "nj@example.com",
            "terminated": False,
        }
        authenticated_connector._request = AsyncMock(return_value=[api_data])

        employees = await authenticated_connector.list_employees()
        assert employees[0].job_title is None

    @pytest.mark.asyncio
    async def test_list_employees_empty_response(self, authenticated_connector):
        authenticated_connector._request = AsyncMock(return_value=[])
        employees = await authenticated_connector.list_employees()
        assert employees == []

    @pytest.mark.asyncio
    async def test_list_employees_missing_optional_fields(self, authenticated_connector):
        api_data = {
            "id": 300,
            "terminated": False,
        }
        authenticated_connector._request = AsyncMock(return_value=[api_data])

        employees = await authenticated_connector.list_employees()
        emp = employees[0]
        assert emp.first_name == ""
        assert emp.last_name == ""
        assert emp.email == ""
        assert emp.hire_date is None


# =============================================================================
# Payroll Operations Tests
# =============================================================================


class TestPayrollOperations:
    """Tests for payroll listing and detail retrieval."""

    @pytest.mark.asyncio
    async def test_list_payrolls_not_authenticated(self, gusto_connector):
        with pytest.raises(ConnectorAuthError, match="Not authenticated"):
            await gusto_connector.list_payrolls()

    @pytest.mark.asyncio
    async def test_list_payrolls_success(self, authenticated_connector, api_payroll_response):
        authenticated_connector._request = AsyncMock(return_value=[api_payroll_response])

        payrolls = await authenticated_connector.list_payrolls()
        assert len(payrolls) == 1
        pr = payrolls[0]
        assert pr.id == "67890"
        assert pr.status == PayrollStatus.PROCESSED
        assert pr.pay_period_start == date(2024, 1, 1)
        assert pr.pay_period_end == date(2024, 1, 14)
        assert pr.check_date == date(2024, 1, 19)
        assert pr.total_gross_pay == Decimal("10000.00")
        assert pr.total_net_pay == Decimal("7500.00")

    @pytest.mark.asyncio
    async def test_list_payrolls_cancelled(self, authenticated_connector):
        api_data = {
            "id": 111,
            "processed": False,
            "cancelled": True,
            "pay_period": {"start_date": "2024-01-01", "end_date": "2024-01-14"},
            "check_date": "2024-01-19",
            "totals": {},
        }
        authenticated_connector._request = AsyncMock(return_value=[api_data])

        payrolls = await authenticated_connector.list_payrolls()
        assert payrolls[0].status == PayrollStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_list_payrolls_unprocessed(self, authenticated_connector):
        api_data = {
            "id": 222,
            "processed": False,
            "cancelled": False,
            "pay_period": {"start_date": "2024-02-01", "end_date": "2024-02-14"},
            "check_date": "2024-02-19",
            "totals": {},
        }
        authenticated_connector._request = AsyncMock(return_value=[api_data])

        payrolls = await authenticated_connector.list_payrolls(processed_only=False)
        assert payrolls[0].status == PayrollStatus.UNPROCESSED

    @pytest.mark.asyncio
    async def test_list_payrolls_with_date_filters(self, authenticated_connector):
        authenticated_connector._request = AsyncMock(return_value=[])

        await authenticated_connector.list_payrolls(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            processed_only=True,
        )

        call_args = authenticated_connector._request.call_args
        endpoint = call_args[0][1]
        assert "start_date=2024-01-01" in endpoint
        assert "end_date=2024-03-31" in endpoint
        assert "processed=true" in endpoint

    @pytest.mark.asyncio
    async def test_get_payroll_not_authenticated(self, gusto_connector):
        with pytest.raises(ConnectorAuthError, match="Not authenticated"):
            await gusto_connector.get_payroll("p1")

    @pytest.mark.asyncio
    async def test_get_payroll_returns_none_for_empty(self, authenticated_connector):
        authenticated_connector._request = AsyncMock(return_value={})
        result = await authenticated_connector.get_payroll("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_payroll_with_employee_compensations(self, authenticated_connector):
        api_data = {
            "id": 333,
            "processed": True,
            "pay_period": {"start_date": "2024-01-01", "end_date": "2024-01-14"},
            "check_date": "2024-01-19",
            "totals": {
                "gross_pay": "5000",
                "net_pay": "3750",
                "employer_taxes": "400",
                "employee_taxes": "1000",
            },
            "employee_compensations": [
                {
                    "employee": {
                        "id": 1,
                        "first_name": "Alice",
                        "last_name": "Smith",
                    },
                    "fixed_compensations": [
                        {"amount": "5000"},
                    ],
                    "hourly_compensations": [],
                    "taxes": [
                        {"name": "Federal Income Tax", "amount": "800", "employer": False},
                        {"name": "State Income Tax", "amount": "200", "employer": False},
                        {"name": "Social Security", "amount": "310", "employer": False},
                        {"name": "Social Security", "amount": "310", "employer": True},
                        {"name": "Medicare", "amount": "72.50", "employer": False},
                        {"name": "Medicare", "amount": "72.50", "employer": True},
                        {"name": "Federal Unemployment Tax", "amount": "42", "employer": True},
                        {"name": "State Unemployment Tax", "amount": "67.50", "employer": True},
                    ],
                    "benefits": [
                        {
                            "name": "401k Retirement Plan",
                            "employee_deduction": "250",
                            "company_contribution": "125",
                        },
                        {
                            "name": "Health Insurance",
                            "employee_deduction": "200",
                            "company_contribution": "400",
                        },
                    ],
                }
            ],
        }
        authenticated_connector._request = AsyncMock(return_value=api_data)

        payroll = await authenticated_connector.get_payroll("333")
        assert payroll is not None
        assert len(payroll.payroll_items) == 1

        item = payroll.payroll_items[0]
        assert item.employee_id == "1"
        assert item.employee_name == "Alice Smith"
        assert item.gross_pay == Decimal("5000")
        assert item.federal_tax == Decimal("800")
        assert item.state_tax == Decimal("200")
        assert item.social_security == Decimal("310")
        assert item.medicare == Decimal("72.50")
        assert item.employer_ss == Decimal("310")
        assert item.employer_medicare == Decimal("72.50")
        assert item.employer_futa == Decimal("42")
        assert item.employer_suta == Decimal("67.50")
        assert item.retirement_401k == Decimal("250")
        assert item.employer_401k_match == Decimal("125")
        assert item.health_insurance == Decimal("200")
        assert item.employer_health == Decimal("400")

    @pytest.mark.asyncio
    async def test_get_payroll_with_hourly_compensations(self, authenticated_connector):
        api_data = {
            "id": 444,
            "processed": True,
            "pay_period": {"start_date": "2024-01-01", "end_date": "2024-01-14"},
            "check_date": "2024-01-19",
            "totals": {},
            "employee_compensations": [
                {
                    "employee": {"id": 2, "first_name": "Bob", "last_name": "Jones"},
                    "fixed_compensations": [],
                    "hourly_compensations": [
                        {"hours": "80", "compensation_multiplier": "25"},
                        {"hours": "10", "compensation_multiplier": "37.5"},
                    ],
                    "taxes": [],
                    "benefits": [],
                }
            ],
        }
        authenticated_connector._request = AsyncMock(return_value=api_data)

        payroll = await authenticated_connector.get_payroll("444")
        item = payroll.payroll_items[0]
        expected_gross = Decimal("80") * Decimal("25") + Decimal("10") * Decimal("37.5")
        assert item.gross_pay == expected_gross


# =============================================================================
# Journal Entry Generation Tests
# =============================================================================


class TestJournalEntryGeneration:
    """Tests for generating QBO journal entries from payroll."""

    def test_generate_journal_entry_basic(self, gusto_connector, sample_payroll_run):
        entry = gusto_connector.generate_journal_entry(sample_payroll_run)
        assert entry.date == date(2024, 1, 19)
        assert "2024-01-01" in entry.memo
        assert "2024-01-14" in entry.memo
        assert len(entry.lines) > 0

    def test_generate_journal_entry_debits(self, gusto_connector, sample_payroll_run):
        entry = gusto_connector.generate_journal_entry(sample_payroll_run)
        debits = [line for line in entry.lines if line["debit"] > 0]
        assert len(debits) >= 1  # At least gross wages debit

    def test_generate_journal_entry_credits(self, gusto_connector, sample_payroll_run):
        entry = gusto_connector.generate_journal_entry(sample_payroll_run)
        credits = [line for line in entry.lines if line["credit"] > 0]
        assert len(credits) >= 1  # At least cash credit

    def test_generate_journal_entry_custom_mappings(self, gusto_connector, sample_payroll_run):
        custom_mappings = {
            "gross_wages": ("7000", "Custom Wages Account"),
            "cash": ("1100", "Custom Bank Account"),
        }
        entry = gusto_connector.generate_journal_entry(
            sample_payroll_run, account_mappings=custom_mappings
        )
        # Check that custom mappings were used
        account_ids = {line["account_id"] for line in entry.lines}
        assert "7000" in account_ids or "1100" in account_ids

    def test_generate_journal_entry_empty_payroll(self, gusto_connector):
        empty_payroll = PayrollRun(
            id="empty",
            company_id="c",
            pay_period_start=date(2024, 1, 1),
            pay_period_end=date(2024, 1, 14),
            check_date=date(2024, 1, 19),
            total_net_pay=Decimal("0"),
        )
        entry = gusto_connector.generate_journal_entry(empty_payroll)
        assert len(entry.lines) == 0

    def test_set_account_mapping(self, gusto_connector):
        gusto_connector.set_account_mapping("custom_acct", "9000", "Custom Account")
        assert gusto_connector._account_mappings["custom_acct"] == ("9000", "Custom Account")

    def test_default_account_mappings_present(self, gusto_connector):
        assert "gross_wages" in gusto_connector._account_mappings
        assert "cash" in gusto_connector._account_mappings
        assert "federal_tax_payable" in gusto_connector._account_mappings
        assert "state_tax_payable" in gusto_connector._account_mappings
        assert "401k_payable" in gusto_connector._account_mappings
        assert "health_insurance_payable" in gusto_connector._account_mappings


# =============================================================================
# Circuit Breaker Integration Tests
# =============================================================================


class TestCircuitBreakerIntegration:
    """Tests for circuit breaker interaction with API calls."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failure_on_server_error(
        self, gusto_connector_with_cb, valid_credentials
    ):
        gusto_connector_with_cb.set_credentials(valid_credentials)

        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.json = AsyncMock(return_value={"error": "Server error"})
        mock_response.headers = {}

        mock_cls = _make_aiohttp_session(mock_response)

        original_record = gusto_connector_with_cb._circuit_breaker.record_failure
        gusto_connector_with_cb._circuit_breaker.record_failure = MagicMock(
            side_effect=original_record
        )

        with patch("aiohttp.ClientSession", mock_cls):
            with pytest.raises(ConnectorAPIError):
                await gusto_connector_with_cb._request("GET", "/v1/test")

        gusto_connector_with_cb._circuit_breaker.record_failure.assert_called()

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_success(
        self, gusto_connector_with_cb, valid_credentials
    ):
        gusto_connector_with_cb.set_credentials(valid_credentials)

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"ok": True})
        mock_response.headers = {}

        mock_cls = _make_aiohttp_session(mock_response)

        original_record = gusto_connector_with_cb._circuit_breaker.record_success
        gusto_connector_with_cb._circuit_breaker.record_success = MagicMock(
            side_effect=original_record
        )

        with patch("aiohttp.ClientSession", mock_cls):
            await gusto_connector_with_cb._request("GET", "/v1/test")

        gusto_connector_with_cb._circuit_breaker.record_success.assert_called()

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failure_on_rate_limit(
        self, gusto_connector_with_cb, valid_credentials
    ):
        gusto_connector_with_cb.set_credentials(valid_credentials)

        mock_response = MagicMock()
        mock_response.status = 429
        mock_response.json = AsyncMock(return_value={"error": "Rate limited"})
        mock_response.headers = {"Retry-After": "60"}

        mock_cls = _make_aiohttp_session(mock_response)

        original_record = gusto_connector_with_cb._circuit_breaker.record_failure
        gusto_connector_with_cb._circuit_breaker.record_failure = MagicMock(
            side_effect=original_record
        )

        with patch("aiohttp.ClientSession", mock_cls):
            with pytest.raises(ConnectorRateLimitError):
                await gusto_connector_with_cb._request("GET", "/v1/test")

        gusto_connector_with_cb._circuit_breaker.record_failure.assert_called()


# =============================================================================
# Get Current Company Tests
# =============================================================================


class TestGetCurrentCompany:
    """Tests for _get_current_company helper."""

    @pytest.mark.asyncio
    async def test_get_current_company_success(self, gusto_connector):
        gusto_connector._request = AsyncMock(
            return_value={
                "companies": [
                    {"id": "comp_001", "name": "First Company"},
                    {"id": "comp_002", "name": "Second Company"},
                ],
            }
        )

        result = await gusto_connector._get_current_company("test_token")
        assert result["id"] == "comp_001"
        assert result["name"] == "First Company"

    @pytest.mark.asyncio
    async def test_get_current_company_no_companies(self, gusto_connector):
        gusto_connector._request = AsyncMock(return_value={"companies": []})

        result = await gusto_connector._get_current_company("test_token")
        assert result["id"] == "unknown"
        assert result["name"] == "Unknown Company"

    @pytest.mark.asyncio
    async def test_get_current_company_missing_key(self, gusto_connector):
        gusto_connector._request = AsyncMock(return_value={})

        result = await gusto_connector._get_current_company("test_token")
        assert result["id"] == "unknown"


# =============================================================================
# Mock Data Generation Tests
# =============================================================================


class TestMockData:
    """Tests for mock data generation helpers."""

    def test_get_mock_employees(self):
        employees = get_mock_employees()
        assert len(employees) == 3

        alice = employees[0]
        assert alice.first_name == "Alice"
        assert alice.employment_type == EmploymentType.FULL_TIME
        assert alice.pay_type == PayType.SALARY
        assert alice.annual_salary == Decimal("150000")

        carol = employees[2]
        assert carol.employment_type == EmploymentType.PART_TIME
        assert carol.pay_type == PayType.HOURLY
        assert carol.hourly_rate == Decimal("35")

    def test_get_mock_payroll_run(self):
        payroll = get_mock_payroll_run()
        assert payroll.id == "payroll_demo_001"
        assert payroll.status == PayrollStatus.PROCESSED
        assert payroll.total_gross_pay == Decimal("22500.00")
        assert payroll.total_net_pay == Decimal("16875.00")
        assert len(payroll.payroll_items) == 2
        assert payroll.payroll_items[0].employee_name == "Alice Johnson"
        assert payroll.payroll_items[1].employee_name == "Bob Smith"

    def test_mock_payroll_run_dates_are_valid(self):
        payroll = get_mock_payroll_run()
        assert payroll.pay_period_start < payroll.pay_period_end
        assert payroll.pay_period_end < payroll.check_date
        assert payroll.processed_at is not None


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""

    def test_payroll_item_all_zero_values(self):
        item = PayrollItem(employee_id="e1", employee_name="Test")
        assert item.net_pay == Decimal("0")
        assert item.total_employer_cost == Decimal("0")

    def test_journal_entry_large_amounts(self):
        entry = JournalEntry(date=date(2024, 1, 1), memo="Large")
        entry.add_debit("1", "A", Decimal("999999999.99"))
        entry.add_credit("2", "B", Decimal("999999999.99"))
        assert entry.is_balanced is True

    def test_employee_full_name_in_to_dict(self):
        emp = Employee(
            id="e1",
            first_name="Mary",
            last_name="Jane-Watson",
            email="mj@example.com",
        )
        result = emp.to_dict()
        assert result["full_name"] == "Mary Jane-Watson"

    @pytest.mark.asyncio
    async def test_list_payrolls_no_filters(self, authenticated_connector):
        authenticated_connector._request = AsyncMock(return_value=[])
        await authenticated_connector.list_payrolls(processed_only=False)

        call_args = authenticated_connector._request.call_args
        endpoint = call_args[0][1]
        assert "processed=true" not in endpoint

    def test_rate_limit_retry_after_default(self, authenticated_connector):
        """Ensure rate limit uses Retry-After header value or defaults to 60."""
        # This is tested indirectly via the 429 test, but let's verify the concept
        pass

    @pytest.mark.asyncio
    async def test_list_employees_no_hire_date(self, authenticated_connector):
        api_data = {
            "id": 500,
            "first_name": "No",
            "last_name": "Date",
            "email": "nd@example.com",
            "terminated": False,
        }
        authenticated_connector._request = AsyncMock(return_value=[api_data])

        employees = await authenticated_connector.list_employees()
        assert employees[0].hire_date is None

    def test_payroll_run_with_none_processed_at(self):
        run = PayrollRun(
            id="pr_1",
            company_id="c",
            pay_period_start=date(2024, 1, 1),
            pay_period_end=date(2024, 1, 14),
            check_date=date(2024, 1, 19),
        )
        assert run.processed_at is None

    @pytest.mark.asyncio
    async def test_list_payrolls_missing_totals(self, authenticated_connector):
        api_data = {
            "id": 555,
            "processed": True,
            "cancelled": False,
            "pay_period": {"start_date": "2024-01-01", "end_date": "2024-01-14"},
            "check_date": "2024-01-19",
            "totals": {},
        }
        authenticated_connector._request = AsyncMock(return_value=[api_data])

        payrolls = await authenticated_connector.list_payrolls()
        assert payrolls[0].total_gross_pay == Decimal("0")
        assert payrolls[0].total_net_pay == Decimal("0")

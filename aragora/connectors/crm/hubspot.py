"""
HubSpot CRM Connector.

Integration with HubSpot CRM API:
- Contacts (create, update, search)
- Companies (create, update, search)
- Deals (pipeline, stages, amounts)
- Engagements (emails, calls, meetings, notes)
- Marketing (emails, forms, campaigns)
- Associations between objects

Requires HubSpot private app access token.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DealStage(str, Enum):
    """Common deal stages (customizable in HubSpot)."""

    APPOINTMENT_SCHEDULED = "appointmentscheduled"
    QUALIFIED_TO_BUY = "qualifiedtobuy"
    PRESENTATION_SCHEDULED = "presentationscheduled"
    DECISION_MAKER_BOUGHT_IN = "decisionmakerboughtin"
    CONTRACT_SENT = "contractsent"
    CLOSED_WON = "closedwon"
    CLOSED_LOST = "closedlost"


class EngagementType(str, Enum):
    """Engagement types."""

    EMAIL = "EMAIL"
    CALL = "CALL"
    MEETING = "MEETING"
    NOTE = "NOTE"
    TASK = "TASK"


class AssociationType(str, Enum):
    """Object association types."""

    CONTACT_TO_COMPANY = "contact_to_company"
    DEAL_TO_CONTACT = "deal_to_contact"
    DEAL_TO_COMPANY = "deal_to_company"


@dataclass
class HubSpotCredentials:
    """HubSpot API credentials."""

    access_token: str
    base_url: str = "https://api.hubapi.com"


@dataclass
class Contact:
    """HubSpot contact."""

    id: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    company: str | None = None
    job_title: str | None = None
    lifecycle_stage: str | None = None
    lead_status: str | None = None
    owner_id: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    archived: bool = False

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Contact:
        """Create from API response."""
        props = data.get("properties", {})
        return cls(
            id=data.get("id", ""),
            email=props.get("email"),
            first_name=props.get("firstname"),
            last_name=props.get("lastname"),
            phone=props.get("phone"),
            company=props.get("company"),
            job_title=props.get("jobtitle"),
            lifecycle_stage=props.get("lifecyclestage"),
            lead_status=props.get("hs_lead_status"),
            owner_id=props.get("hubspot_owner_id"),
            properties=props,
            created_at=_parse_datetime(props.get("createdate")),
            updated_at=_parse_datetime(props.get("lastmodifieddate")),
            archived=data.get("archived", False),
        )


@dataclass
class Company:
    """HubSpot company."""

    id: str
    name: str | None = None
    domain: str | None = None
    industry: str | None = None
    phone: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    num_employees: int | None = None
    annual_revenue: Decimal | None = None
    lifecycle_stage: str | None = None
    owner_id: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    archived: bool = False

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Company:
        """Create from API response."""
        props = data.get("properties", {})
        revenue = props.get("annualrevenue")
        return cls(
            id=data.get("id", ""),
            name=props.get("name"),
            domain=props.get("domain"),
            industry=props.get("industry"),
            phone=props.get("phone"),
            city=props.get("city"),
            state=props.get("state"),
            country=props.get("country"),
            num_employees=(
                int(props["numberofemployees"]) if props.get("numberofemployees") else None
            ),
            annual_revenue=Decimal(str(revenue)) if revenue else None,
            lifecycle_stage=props.get("lifecyclestage"),
            owner_id=props.get("hubspot_owner_id"),
            properties=props,
            created_at=_parse_datetime(props.get("createdate")),
            updated_at=_parse_datetime(props.get("hs_lastmodifieddate")),
            archived=data.get("archived", False),
        )


@dataclass
class Deal:
    """HubSpot deal."""

    id: str
    name: str | None = None
    amount: Decimal | None = None
    stage: str | None = None
    pipeline: str | None = None
    close_date: datetime | None = None
    deal_type: str | None = None
    owner_id: str | None = None
    priority: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    archived: bool = False

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Deal:
        """Create from API response."""
        props = data.get("properties", {})
        amount = props.get("amount")
        return cls(
            id=data.get("id", ""),
            name=props.get("dealname"),
            amount=Decimal(str(amount)) if amount else None,
            stage=props.get("dealstage"),
            pipeline=props.get("pipeline"),
            close_date=_parse_datetime(props.get("closedate")),
            deal_type=props.get("dealtype"),
            owner_id=props.get("hubspot_owner_id"),
            priority=props.get("hs_priority"),
            properties=props,
            created_at=_parse_datetime(props.get("createdate")),
            updated_at=_parse_datetime(props.get("hs_lastmodifieddate")),
            archived=data.get("archived", False),
        )


@dataclass
class Engagement:
    """HubSpot engagement (email, call, meeting, note, task)."""

    id: str
    type: EngagementType
    owner_id: str | None = None
    timestamp: datetime | None = None
    subject: str | None = None
    body: str | None = None
    direction: str | None = None  # INBOUND or OUTBOUND
    duration_ms: int | None = None
    status: str | None = None
    associated_contact_ids: list[str] = field(default_factory=list)
    associated_company_ids: list[str] = field(default_factory=list)
    associated_deal_ids: list[str] = field(default_factory=list)
    created_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Engagement:
        """Create from API response."""
        engagement = data.get("engagement", {})
        metadata = data.get("metadata", {})
        associations = data.get("associations", {})

        return cls(
            id=str(engagement.get("id", "")),
            type=EngagementType(engagement.get("type", "NOTE")),
            owner_id=str(engagement.get("ownerId")) if engagement.get("ownerId") else None,
            timestamp=_from_timestamp(engagement.get("timestamp")),
            subject=metadata.get("subject"),
            body=metadata.get("body") or metadata.get("text"),
            direction=metadata.get("direction"),
            duration_ms=metadata.get("durationMilliseconds"),
            status=metadata.get("status"),
            associated_contact_ids=[str(i) for i in associations.get("contactIds", [])],
            associated_company_ids=[str(i) for i in associations.get("companyIds", [])],
            associated_deal_ids=[str(i) for i in associations.get("dealIds", [])],
            created_at=_from_timestamp(engagement.get("createdAt")),
        )


@dataclass
class Pipeline:
    """HubSpot pipeline (for deals)."""

    id: str
    label: str
    display_order: int = 0
    active: bool = True
    stages: list[PipelineStage] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Pipeline:
        """Create from API response."""
        return cls(
            id=data.get("id", ""),
            label=data.get("label", ""),
            display_order=data.get("displayOrder", 0),
            active=data.get("archived", True) is False,
            stages=[PipelineStage.from_api(s) for s in data.get("stages", [])],
        )


@dataclass
class PipelineStage:
    """Pipeline stage."""

    id: str
    label: str
    display_order: int = 0
    probability: float = 0.0
    closed_won: bool = False

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PipelineStage:
        """Create from API response."""
        metadata = data.get("metadata", {})
        return cls(
            id=data.get("id", ""),
            label=data.get("label", ""),
            display_order=data.get("displayOrder", 0),
            probability=float(metadata.get("probability", 0)),
            closed_won=metadata.get("isClosed", False) and metadata.get("probability", 0) == 1.0,
        )


@dataclass
class Owner:
    """HubSpot owner (user)."""

    id: str
    email: str
    first_name: str
    last_name: str
    user_id: int | None = None
    teams: list[dict[str, Any]] = field(default_factory=list)
    archived: bool = False

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Owner:
        """Create from API response."""
        return cls(
            id=data.get("id", ""),
            email=data.get("email", ""),
            first_name=data.get("firstName", ""),
            last_name=data.get("lastName", ""),
            user_id=data.get("userId"),
            teams=data.get("teams", []),
            archived=data.get("archived", False),
        )


class HubSpotError(Exception):
    """HubSpot API error."""

    def __init__(self, message: str, status_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


class HubSpotConnector:
    """
    HubSpot CRM API connector.

    Provides integration with HubSpot for:
    - Contact management
    - Company management
    - Deal pipeline tracking
    - Engagement logging (emails, calls, meetings)
    - Marketing email and campaigns
    """

    def __init__(self, credentials: HubSpotCredentials):
        self.credentials = credentials
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.credentials.base_url,
                headers={
                    "Authorization": f"Bearer {self.credentials.access_token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    # Retry configuration
    _MAX_RETRIES = 3
    _BASE_DELAY = 1.0  # seconds
    _MAX_DELAY = 30.0  # seconds

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_data: Any = None,
    ) -> dict[str, Any]:
        """Make API request with retry and exponential backoff.

        Retries on 429 (rate limit) and 5xx (server error) responses,
        as well as transient network errors, up to ``_MAX_RETRIES`` times.
        """
        last_exc: Exception | None = None

        for attempt in range(self._MAX_RETRIES + 1):
            try:
                client = await self._get_client()
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json_data,
                )

                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self._MAX_RETRIES:
                        delay = min(
                            self._BASE_DELAY * (2**attempt),
                            self._MAX_DELAY,
                        )
                        jitter = delay * 0.3 * random.random()
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                delay = float(retry_after)
                            except (ValueError, TypeError):
                                raise HubSpotError(
                                    f"Invalid Retry-After header: {retry_after!r}",
                                    status_code=response.status_code,
                                    details={"retry_after": retry_after},
                                ) from None
                        logger.warning(
                            "HubSpot %s %s returned %d, retrying in %.1fs (attempt %d/%d)",
                            method,
                            path,
                            response.status_code,
                            delay + jitter,
                            attempt + 1,
                            self._MAX_RETRIES,
                        )
                        await asyncio.sleep(delay + jitter)
                        continue

                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        raise HubSpotError(
                            message=error_data.get("message", response.text),
                            status_code=response.status_code,
                            details=error_data,
                        )
                    except ValueError:
                        raise HubSpotError(
                            f"HTTP {response.status_code}: {response.text}",
                            status_code=response.status_code,
                        )

                if response.status_code == 204:
                    return {}
                return response.json()

            except HubSpotError:
                raise
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                OSError,
            ) as e:
                last_exc = e
                if attempt < self._MAX_RETRIES:
                    delay = min(
                        self._BASE_DELAY * (2**attempt),
                        self._MAX_DELAY,
                    )
                    jitter = delay * 0.3 * random.random()
                    logger.warning(
                        "HubSpot %s %s network error: %s, retrying in %.1fs (attempt %d/%d)",
                        method,
                        path,
                        type(e).__name__,
                        delay + jitter,
                        attempt + 1,
                        self._MAX_RETRIES,
                    )
                    await asyncio.sleep(delay + jitter)
                    continue
                raise HubSpotError(
                    f"Network error after {self._MAX_RETRIES} retries: {type(e).__name__}",
                ) from e

        raise HubSpotError(
            f"Request failed after {self._MAX_RETRIES} retries",
        ) from last_exc

    # =========================================================================
    # Contacts
    # =========================================================================

    async def get_contacts(
        self,
        limit: int = 100,
        after: str | None = None,
        properties: list[str] | None = None,
    ) -> tuple[list[Contact], str | None]:
        """Get contacts. Returns (contacts, next_after)."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if after:
            params["after"] = after
        if properties:
            params["properties"] = ",".join(properties)
        else:
            params["properties"] = (
                "firstname,lastname,email,phone,company,jobtitle,lifecyclestage,hs_lead_status,hubspot_owner_id,createdate,lastmodifieddate"
            )

        data = await self._request("GET", "/crm/v3/objects/contacts", params=params)
        contacts = [Contact.from_api(c) for c in data.get("results", [])]
        next_after = data.get("paging", {}).get("next", {}).get("after")
        return contacts, next_after

    async def get_contact(self, contact_id: str, properties: list[str] | None = None) -> Contact:
        """Get a single contact."""
        params: dict[str, Any] = {}
        if properties:
            params["properties"] = ",".join(properties)
        else:
            params["properties"] = (
                "firstname,lastname,email,phone,company,jobtitle,lifecyclestage,hs_lead_status,hubspot_owner_id,createdate,lastmodifieddate"
            )

        data = await self._request("GET", f"/crm/v3/objects/contacts/{contact_id}", params=params)
        return Contact.from_api(data)

    async def create_contact(
        self,
        email: str,
        first_name: str | None = None,
        last_name: str | None = None,
        phone: str | None = None,
        company: str | None = None,
        job_title: str | None = None,
        lifecycle_stage: str | None = None,
        owner_id: str | None = None,
        custom_properties: dict[str, Any] | None = None,
    ) -> Contact:
        """Create a new contact."""
        properties: dict[str, Any] = {"email": email}

        if first_name:
            properties["firstname"] = first_name
        if last_name:
            properties["lastname"] = last_name
        if phone:
            properties["phone"] = phone
        if company:
            properties["company"] = company
        if job_title:
            properties["jobtitle"] = job_title
        if lifecycle_stage:
            properties["lifecyclestage"] = lifecycle_stage
        if owner_id:
            properties["hubspot_owner_id"] = owner_id
        if custom_properties:
            properties.update(custom_properties)

        data = await self._request(
            "POST", "/crm/v3/objects/contacts", json_data={"properties": properties}
        )
        return Contact.from_api(data)

    async def update_contact(
        self,
        contact_id: str,
        properties: dict[str, Any],
    ) -> Contact:
        """Update a contact."""
        data = await self._request(
            "PATCH",
            f"/crm/v3/objects/contacts/{contact_id}",
            json_data={"properties": properties},
        )
        return Contact.from_api(data)

    async def delete_contact(self, contact_id: str) -> bool:
        """Archive (soft delete) a contact."""
        await self._request("DELETE", f"/crm/v3/objects/contacts/{contact_id}")
        return True

    async def search_contacts(
        self,
        query: str | None = None,
        filters: list[dict[str, Any]] | None = None,
        limit: int = 100,
    ) -> list[Contact]:
        """
        Search contacts.

        filters format:
        [
            {"propertyName": "email", "operator": "CONTAINS_TOKEN", "value": "example.com"},
            {"propertyName": "lifecyclestage", "operator": "EQ", "value": "lead"}
        ]
        """
        search_data: dict[str, Any] = {
            "limit": min(limit, 100),
            "properties": [
                "firstname",
                "lastname",
                "email",
                "phone",
                "company",
                "jobtitle",
                "lifecyclestage",
            ],
        }

        if query:
            search_data["query"] = query
        if filters:
            search_data["filterGroups"] = [{"filters": filters}]

        data = await self._request("POST", "/crm/v3/objects/contacts/search", json_data=search_data)
        return [Contact.from_api(c) for c in data.get("results", [])]

    # =========================================================================
    # Companies
    # =========================================================================

    async def get_companies(
        self,
        limit: int = 100,
        after: str | None = None,
    ) -> tuple[list[Company], str | None]:
        """Get companies. Returns (companies, next_after)."""
        params: dict[str, Any] = {
            "limit": min(limit, 100),
            "properties": "name,domain,industry,phone,city,state,country,numberofemployees,annualrevenue,lifecyclestage,hubspot_owner_id,createdate,hs_lastmodifieddate",
        }
        if after:
            params["after"] = after

        data = await self._request("GET", "/crm/v3/objects/companies", params=params)
        companies = [Company.from_api(c) for c in data.get("results", [])]
        next_after = data.get("paging", {}).get("next", {}).get("after")
        return companies, next_after

    async def get_company(self, company_id: str) -> Company:
        """Get a single company."""
        params = {
            "properties": "name,domain,industry,phone,city,state,country,numberofemployees,annualrevenue,lifecyclestage,hubspot_owner_id,createdate,hs_lastmodifieddate"
        }
        data = await self._request("GET", f"/crm/v3/objects/companies/{company_id}", params=params)
        return Company.from_api(data)

    async def create_company(
        self,
        name: str,
        domain: str | None = None,
        industry: str | None = None,
        phone: str | None = None,
        city: str | None = None,
        state: str | None = None,
        country: str | None = None,
        num_employees: int | None = None,
        annual_revenue: Decimal | None = None,
        owner_id: str | None = None,
        custom_properties: dict[str, Any] | None = None,
    ) -> Company:
        """Create a new company."""
        properties: dict[str, Any] = {"name": name}

        if domain:
            properties["domain"] = domain
        if industry:
            properties["industry"] = industry
        if phone:
            properties["phone"] = phone
        if city:
            properties["city"] = city
        if state:
            properties["state"] = state
        if country:
            properties["country"] = country
        if num_employees is not None:
            properties["numberofemployees"] = str(num_employees)
        if annual_revenue is not None:
            properties["annualrevenue"] = str(annual_revenue)
        if owner_id:
            properties["hubspot_owner_id"] = owner_id
        if custom_properties:
            properties.update(custom_properties)

        data = await self._request(
            "POST", "/crm/v3/objects/companies", json_data={"properties": properties}
        )
        return Company.from_api(data)

    async def update_company(
        self,
        company_id: str,
        properties: dict[str, Any],
    ) -> Company:
        """Update a company."""
        data = await self._request(
            "PATCH",
            f"/crm/v3/objects/companies/{company_id}",
            json_data={"properties": properties},
        )
        return Company.from_api(data)

    async def search_companies(
        self,
        query: str | None = None,
        filters: list[dict[str, Any]] | None = None,
        limit: int = 100,
    ) -> list[Company]:
        """Search companies."""
        search_data: dict[str, Any] = {
            "limit": min(limit, 100),
            "properties": ["name", "domain", "industry", "phone", "city", "state", "country"],
        }

        if query:
            search_data["query"] = query
        if filters:
            search_data["filterGroups"] = [{"filters": filters}]

        data = await self._request(
            "POST", "/crm/v3/objects/companies/search", json_data=search_data
        )
        return [Company.from_api(c) for c in data.get("results", [])]

    # =========================================================================
    # Deals
    # =========================================================================

    async def get_deals(
        self,
        limit: int = 100,
        after: str | None = None,
    ) -> tuple[list[Deal], str | None]:
        """Get deals. Returns (deals, next_after)."""
        params: dict[str, Any] = {
            "limit": min(limit, 100),
            "properties": "dealname,amount,dealstage,pipeline,closedate,dealtype,hubspot_owner_id,hs_priority,createdate,hs_lastmodifieddate",
        }
        if after:
            params["after"] = after

        data = await self._request("GET", "/crm/v3/objects/deals", params=params)
        deals = [Deal.from_api(d) for d in data.get("results", [])]
        next_after = data.get("paging", {}).get("next", {}).get("after")
        return deals, next_after

    async def get_deal(self, deal_id: str) -> Deal:
        """Get a single deal."""
        params = {
            "properties": "dealname,amount,dealstage,pipeline,closedate,dealtype,hubspot_owner_id,hs_priority,createdate,hs_lastmodifieddate"
        }
        data = await self._request("GET", f"/crm/v3/objects/deals/{deal_id}", params=params)
        return Deal.from_api(data)

    async def create_deal(
        self,
        name: str,
        stage: str,
        pipeline: str = "default",
        amount: Decimal | None = None,
        close_date: datetime | None = None,
        deal_type: str | None = None,
        owner_id: str | None = None,
        priority: str | None = None,
        custom_properties: dict[str, Any] | None = None,
    ) -> Deal:
        """Create a new deal."""
        properties: dict[str, Any] = {
            "dealname": name,
            "dealstage": stage,
            "pipeline": pipeline,
        }

        if amount is not None:
            properties["amount"] = str(amount)
        if close_date:
            properties["closedate"] = close_date.strftime("%Y-%m-%d")
        if deal_type:
            properties["dealtype"] = deal_type
        if owner_id:
            properties["hubspot_owner_id"] = owner_id
        if priority:
            properties["hs_priority"] = priority
        if custom_properties:
            properties.update(custom_properties)

        data = await self._request(
            "POST", "/crm/v3/objects/deals", json_data={"properties": properties}
        )
        return Deal.from_api(data)

    async def update_deal(
        self,
        deal_id: str,
        properties: dict[str, Any],
    ) -> Deal:
        """Update a deal."""
        data = await self._request(
            "PATCH",
            f"/crm/v3/objects/deals/{deal_id}",
            json_data={"properties": properties},
        )
        return Deal.from_api(data)

    async def move_deal_stage(self, deal_id: str, stage: str) -> Deal:
        """Move a deal to a different stage."""
        return await self.update_deal(deal_id, {"dealstage": stage})

    # =========================================================================
    # Pipelines
    # =========================================================================

    async def get_pipelines(self, object_type: str = "deals") -> list[Pipeline]:
        """Get all pipelines for an object type."""
        data = await self._request("GET", f"/crm/v3/pipelines/{object_type}")
        return [Pipeline.from_api(p) for p in data.get("results", [])]

    async def get_pipeline(self, object_type: str, pipeline_id: str) -> Pipeline:
        """Get a single pipeline."""
        data = await self._request("GET", f"/crm/v3/pipelines/{object_type}/{pipeline_id}")
        return Pipeline.from_api(data)

    # =========================================================================
    # Associations
    # =========================================================================

    async def create_association(
        self,
        from_object_type: str,
        from_object_id: str,
        to_object_type: str,
        to_object_id: str,
        association_type: str | None = None,
    ) -> bool:
        """Create an association between two objects."""
        association_data = [
            {
                "to": {"id": to_object_id},
                "types": [
                    {
                        "associationCategory": "HUBSPOT_DEFINED",
                        "associationTypeId": association_type
                        or self._get_default_association_type(from_object_type, to_object_type),
                    }
                ],
            }
        ]

        await self._request(
            "PUT",
            f"/crm/v4/objects/{from_object_type}/{from_object_id}/associations/{to_object_type}",
            json_data=association_data,
        )
        return True

    def _get_default_association_type(self, from_type: str, to_type: str) -> int:
        """Get default association type ID."""
        # HubSpot default association type IDs
        associations = {
            ("contacts", "companies"): 1,
            ("deals", "contacts"): 3,
            ("deals", "companies"): 5,
            ("contacts", "deals"): 4,
            ("companies", "contacts"): 2,
            ("companies", "deals"): 6,
        }
        return associations.get((from_type, to_type), 1)

    async def get_associated_objects(
        self,
        object_type: str,
        object_id: str,
        to_object_type: str,
    ) -> list[str]:
        """Get IDs of associated objects."""
        data = await self._request(
            "GET",
            f"/crm/v4/objects/{object_type}/{object_id}/associations/{to_object_type}",
        )
        return [r.get("toObjectId", "") for r in data.get("results", [])]

    # =========================================================================
    # Engagements
    # =========================================================================

    async def create_engagement(
        self,
        engagement_type: EngagementType,
        owner_id: str | None = None,
        timestamp: datetime | None = None,
        subject: str | None = None,
        body: str | None = None,
        contact_ids: list[str] | None = None,
        company_ids: list[str] | None = None,
        deal_ids: list[str] | None = None,
    ) -> Engagement:
        """Create an engagement (email, call, meeting, note)."""
        engagement_data: dict[str, Any] = {
            "engagement": {
                "type": engagement_type.value,
                "timestamp": int((timestamp or datetime.now()).timestamp() * 1000),
            },
            "metadata": {},
            "associations": {
                "contactIds": [int(i) for i in contact_ids or []],
                "companyIds": [int(i) for i in company_ids or []],
                "dealIds": [int(i) for i in deal_ids or []],
            },
        }

        if owner_id:
            engagement_data["engagement"]["ownerId"] = int(owner_id)

        if subject:
            engagement_data["metadata"]["subject"] = subject
        if body:
            if engagement_type == EngagementType.NOTE:
                engagement_data["metadata"]["body"] = body
            else:
                engagement_data["metadata"]["text"] = body

        data = await self._request(
            "POST",
            "/engagements/v1/engagements",
            json_data=engagement_data,
        )
        return Engagement.from_api(data)

    async def get_engagement(self, engagement_id: str) -> Engagement:
        """Get a single engagement."""
        data = await self._request("GET", f"/engagements/v1/engagements/{engagement_id}")
        return Engagement.from_api(data)

    async def log_email(
        self,
        subject: str,
        body: str,
        contact_ids: list[str] | None = None,
        owner_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> Engagement:
        """Log an email engagement."""
        return await self.create_engagement(
            engagement_type=EngagementType.EMAIL,
            subject=subject,
            body=body,
            contact_ids=contact_ids,
            owner_id=owner_id,
            timestamp=timestamp,
        )

    async def log_call(
        self,
        body: str,
        contact_ids: list[str] | None = None,
        owner_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> Engagement:
        """Log a call engagement."""
        return await self.create_engagement(
            engagement_type=EngagementType.CALL,
            body=body,
            contact_ids=contact_ids,
            owner_id=owner_id,
            timestamp=timestamp,
        )

    async def add_note(
        self,
        body: str,
        contact_ids: list[str] | None = None,
        company_ids: list[str] | None = None,
        deal_ids: list[str] | None = None,
        owner_id: str | None = None,
    ) -> Engagement:
        """Add a note to contact/company/deal."""
        return await self.create_engagement(
            engagement_type=EngagementType.NOTE,
            body=body,
            contact_ids=contact_ids,
            company_ids=company_ids,
            deal_ids=deal_ids,
            owner_id=owner_id,
        )

    # =========================================================================
    # Owners
    # =========================================================================

    async def get_owners(self) -> list[Owner]:
        """Get all owners (users)."""
        data = await self._request("GET", "/crm/v3/owners")
        return [Owner.from_api(o) for o in data.get("results", [])]

    async def get_owner(self, owner_id: str) -> Owner:
        """Get a single owner."""
        data = await self._request("GET", f"/crm/v3/owners/{owner_id}")
        return Owner.from_api(data)

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> HubSpotConnector:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid HubSpot datetime value: {value!r}") from exc


def _from_timestamp(value: int | None) -> datetime | None:
    """Convert millisecond timestamp to datetime."""
    if value is None:
        return None
    try:
        if isinstance(value, bool):
            raise TypeError("Boolean values are not valid timestamps")
        return datetime.fromtimestamp(value / 1000)
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError(f"Invalid HubSpot timestamp value: {value!r}") from exc


def get_mock_contact() -> Contact:
    """Get a mock contact for testing."""
    return Contact(
        id="12345",
        email="john.doe@example.com",
        first_name="John",
        last_name="Doe",
        company="Example Corp",
        job_title="Software Engineer",
        lifecycle_stage="lead",
    )


def get_mock_deal() -> Deal:
    """Get a mock deal for testing."""
    return Deal(
        id="67890",
        name="Enterprise Deal",
        amount=Decimal("50000.00"),
        stage="contractsent",
        pipeline="default",
        close_date=datetime.now(),
    )

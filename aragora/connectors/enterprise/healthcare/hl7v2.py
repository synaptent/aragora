"""
HL7 v2.x Healthcare Connector.

HIPAA-compliant integration for HL7 v2 pipe-delimited messages:
- Segment parsing (MSH, PID, PV1, OBX, ORC)
- Message type handling (ADT, ORM, ORU, SIU)
- MLLP transport protocol support
- PHI redaction using Safe Harbor method
- Comprehensive audit logging for compliance
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from collections.abc import AsyncIterator

from aragora.connectors.base import Evidence
from aragora.connectors.enterprise.base import (
    EnterpriseConnector,
    SyncItem,
    SyncState,
)
from aragora.reasoning.provenance import SourceType

logger = logging.getLogger(__name__)

_MAX_PAGES = 1000  # Safety cap for pagination loops

# =============================================================================
# HL7 v2 Constants
# =============================================================================

# Default encoding characters (MSH-2)
DEFAULT_FIELD_SEPARATOR = "|"
DEFAULT_ENCODING_CHARS = "^~\\&"  # Component, Repetition, Escape, Subcomponent

# MLLP framing
MLLP_START_BLOCK = b"\x0b"  # VT (vertical tab)
MLLP_END_BLOCK = b"\x1c"  # FS (file separator)
MLLP_CARRIAGE_RETURN = b"\x0d"  # CR


class HL7MessageType(str, Enum):
    """HL7 v2 message types."""

    # Admission/Discharge/Transfer
    ADT = "ADT"  # Patient administration
    ADT_A01 = "ADT^A01"  # Admit/visit notification
    ADT_A02 = "ADT^A02"  # Transfer a patient
    ADT_A03 = "ADT^A03"  # Discharge/end visit
    ADT_A04 = "ADT^A04"  # Register a patient
    ADT_A08 = "ADT^A08"  # Update patient information
    ADT_A11 = "ADT^A11"  # Cancel admit
    ADT_A28 = "ADT^A28"  # Add person information
    ADT_A31 = "ADT^A31"  # Update person information

    # Orders
    ORM = "ORM"  # General order message
    ORM_O01 = "ORM^O01"  # Order message

    # Results
    ORU = "ORU"  # Observation result (unsolicited)
    ORU_R01 = "ORU^R01"  # Unsolicited observation message

    # Scheduling
    SIU = "SIU"  # Scheduling information (unsolicited)
    SIU_S12 = "SIU^S12"  # Notification of new appointment
    SIU_S13 = "SIU^S13"  # Notification of rescheduled appointment
    SIU_S14 = "SIU^S14"  # Notification of appointment modification
    SIU_S15 = "SIU^S15"  # Notification of appointment cancellation

    # Queries
    QRY = "QRY"  # Query message
    QRY_A19 = "QRY^A19"  # Patient query

    # Master Files
    MFN = "MFN"  # Master files notification


class HL7SegmentType(str, Enum):
    """HL7 v2 segment types."""

    MSH = "MSH"  # Message Header
    EVN = "EVN"  # Event Type
    PID = "PID"  # Patient Identification
    PV1 = "PV1"  # Patient Visit
    PV2 = "PV2"  # Patient Visit - Additional Info
    NK1 = "NK1"  # Next of Kin
    OBR = "OBR"  # Observation Request
    OBX = "OBX"  # Observation/Result
    ORC = "ORC"  # Common Order
    DG1 = "DG1"  # Diagnosis
    AL1 = "AL1"  # Allergy Information
    IN1 = "IN1"  # Insurance
    GT1 = "GT1"  # Guarantor
    NTE = "NTE"  # Notes and Comments
    SCH = "SCH"  # Scheduling Activity
    RGS = "RGS"  # Resource Group
    AIS = "AIS"  # Appointment Information - Service
    AIL = "AIL"  # Appointment Information - Location
    AIP = "AIP"  # Appointment Information - Personnel


# =============================================================================
# HL7 v2 Data Structures
# =============================================================================


@dataclass
class HL7Field:
    """Represents a single HL7 field with components and subcomponents."""

    value: str
    components: list[str] = field(default_factory=list)
    repetitions: list[HL7Field] = field(default_factory=list)

    @classmethod
    def parse(
        cls,
        raw: str,
        component_sep: str = "^",
        repetition_sep: str = "~",
        subcomponent_sep: str = "&",
    ) -> HL7Field:
        """Parse a field value into components and repetitions."""
        # Handle repetitions first
        if repetition_sep in raw:
            parts = raw.split(repetition_sep)
            first = cls.parse(parts[0], component_sep, repetition_sep, subcomponent_sep)
            first.repetitions = [
                cls.parse(p, component_sep, repetition_sep, subcomponent_sep) for p in parts[1:]
            ]
            return first

        # Parse components
        components = raw.split(component_sep) if component_sep in raw else [raw]

        return cls(value=raw, components=components)

    def get_component(self, index: int, default: str = "") -> str:
        """Get component by index (1-based)."""
        if 0 < index <= len(self.components):
            return self.components[index - 1]
        return default

    def __str__(self) -> str:
        return self.value


@dataclass
class HL7Segment:
    """Represents an HL7 segment with fields."""

    segment_type: str
    fields: list[HL7Field] = field(default_factory=list)
    raw: str = ""

    @classmethod
    def parse(
        cls,
        raw: str,
        field_sep: str = "|",
        encoding_chars: str = "^~\\&",
    ) -> HL7Segment:
        """Parse a segment line into fields."""
        if not raw:
            raise ValueError("Empty segment")

        component_sep = encoding_chars[0] if len(encoding_chars) > 0 else "^"
        repetition_sep = encoding_chars[1] if len(encoding_chars) > 1 else "~"
        subcomponent_sep = encoding_chars[3] if len(encoding_chars) > 3 else "&"

        parts = raw.split(field_sep)
        segment_type = parts[0]

        # MSH is special - field separator is MSH-1
        if segment_type == "MSH":
            fields = [
                HL7Field(value=field_sep),  # MSH-1 is the field separator
                HL7Field(value=encoding_chars),  # MSH-2 is encoding chars
            ]
            # Parse remaining fields
            for part in parts[2:]:
                fields.append(HL7Field.parse(part, component_sep, repetition_sep, subcomponent_sep))
        else:
            fields = [
                HL7Field.parse(part, component_sep, repetition_sep, subcomponent_sep)
                for part in parts[1:]
            ]

        return cls(segment_type=segment_type, fields=fields, raw=raw)

    def get_field(self, index: int) -> HL7Field | None:
        """Get field by index (1-based)."""
        if 0 < index <= len(self.fields):
            return self.fields[index - 1]
        return None

    def get_field_value(self, index: int, default: str = "") -> str:
        """Get field value by index (1-based)."""
        f = self.get_field(index)
        return f.value if f else default

    def get_component(self, field_index: int, component_index: int, default: str = "") -> str:
        """Get component value (both indices 1-based)."""
        f = self.get_field(field_index)
        if f:
            return f.get_component(component_index, default)
        return default


@dataclass
class MSHSegment:
    """Message Header segment."""

    field_separator: str = "|"
    encoding_characters: str = "^~\\&"
    sending_application: str = ""
    sending_facility: str = ""
    receiving_application: str = ""
    receiving_facility: str = ""
    message_datetime: datetime | None = None
    security: str = ""
    message_type: str = ""
    message_control_id: str = ""
    processing_id: str = ""
    version_id: str = "2.5.1"

    @classmethod
    def from_segment(cls, segment: HL7Segment) -> MSHSegment:
        """Create MSH from parsed segment."""
        # Parse datetime from MSH-7
        dt_str = segment.get_field_value(7)
        msg_dt = None
        if dt_str:
            try:
                # HL7 datetime format: YYYYMMDDHHMMSS or YYYYMMDDHHMM
                if len(dt_str) >= 14:
                    msg_dt = datetime.strptime(dt_str[:14], "%Y%m%d%H%M%S")
                elif len(dt_str) >= 12:
                    msg_dt = datetime.strptime(dt_str[:12], "%Y%m%d%H%M")
                elif len(dt_str) >= 8:
                    msg_dt = datetime.strptime(dt_str[:8], "%Y%m%d")
            except ValueError as e:
                logger.debug("from segment encountered an error: %s", e)

        return cls(
            field_separator=segment.get_field_value(1, "|"),
            encoding_characters=segment.get_field_value(2, "^~\\&"),
            sending_application=segment.get_component(3, 1),
            sending_facility=segment.get_component(4, 1),
            receiving_application=segment.get_component(5, 1),
            receiving_facility=segment.get_component(6, 1),
            message_datetime=msg_dt,
            security=segment.get_field_value(8),
            message_type=segment.get_field_value(9),
            message_control_id=segment.get_field_value(10),
            processing_id=segment.get_field_value(11),
            version_id=segment.get_field_value(12),
        )


@dataclass
class PIDSegment:
    """Patient Identification segment."""

    set_id: str = ""
    patient_id: str = ""  # PID-2 (deprecated)
    patient_identifier_list: list[str] = field(default_factory=list)  # PID-3
    alternate_patient_id: str = ""  # PID-4
    patient_name: str = ""  # PID-5
    mothers_maiden_name: str = ""  # PID-6
    date_of_birth: datetime | None = None  # PID-7
    administrative_sex: str = ""  # PID-8
    patient_alias: str = ""  # PID-9
    race: str = ""  # PID-10
    patient_address: str = ""  # PID-11
    county_code: str = ""  # PID-12
    phone_home: str = ""  # PID-13
    phone_business: str = ""  # PID-14
    primary_language: str = ""  # PID-15
    marital_status: str = ""  # PID-16
    religion: str = ""  # PID-17
    patient_account_number: str = ""  # PID-18
    ssn: str = ""  # PID-19

    @classmethod
    def from_segment(cls, segment: HL7Segment) -> PIDSegment:
        """Create PID from parsed segment."""
        # Parse date of birth
        dob_str = segment.get_field_value(7)
        dob = None
        if dob_str:
            try:
                if len(dob_str) >= 8:
                    dob = datetime.strptime(dob_str[:8], "%Y%m%d")
            except ValueError as e:
                logger.debug("from segment encountered an error: %s", e)

        # Parse patient identifiers (repeating field)
        pid3 = segment.get_field(3)
        identifiers = []
        if pid3:
            identifiers.append(pid3.get_component(1))
            for rep in pid3.repetitions:
                identifiers.append(rep.get_component(1))

        return cls(
            set_id=segment.get_field_value(1),
            patient_id=segment.get_field_value(2),
            patient_identifier_list=identifiers,
            alternate_patient_id=segment.get_field_value(4),
            patient_name=segment.get_field_value(5),
            mothers_maiden_name=segment.get_field_value(6),
            date_of_birth=dob,
            administrative_sex=segment.get_field_value(8),
            patient_alias=segment.get_field_value(9),
            race=segment.get_field_value(10),
            patient_address=segment.get_field_value(11),
            county_code=segment.get_field_value(12),
            phone_home=segment.get_field_value(13),
            phone_business=segment.get_field_value(14),
            primary_language=segment.get_field_value(15),
            marital_status=segment.get_field_value(16),
            religion=segment.get_field_value(17),
            patient_account_number=segment.get_field_value(18),
            ssn=segment.get_field_value(19),
        )


@dataclass
class PV1Segment:
    """Patient Visit segment."""

    set_id: str = ""
    patient_class: str = ""  # PV1-2 (I=inpatient, O=outpatient, E=emergency)
    assigned_patient_location: str = ""  # PV1-3
    admission_type: str = ""  # PV1-4
    preadmit_number: str = ""  # PV1-5
    prior_patient_location: str = ""  # PV1-6
    attending_doctor: str = ""  # PV1-7
    referring_doctor: str = ""  # PV1-8
    consulting_doctor: str = ""  # PV1-9
    hospital_service: str = ""  # PV1-10
    admit_datetime: datetime | None = None  # PV1-44
    discharge_datetime: datetime | None = None  # PV1-45
    visit_number: str = ""  # PV1-19

    @classmethod
    def from_segment(cls, segment: HL7Segment) -> PV1Segment:
        """Create PV1 from parsed segment."""
        # Parse admit datetime (PV1-44)
        admit_str = segment.get_field_value(44)
        admit_dt = None
        if admit_str:
            try:
                if len(admit_str) >= 14:
                    admit_dt = datetime.strptime(admit_str[:14], "%Y%m%d%H%M%S")
                elif len(admit_str) >= 8:
                    admit_dt = datetime.strptime(admit_str[:8], "%Y%m%d")
            except ValueError as e:
                logger.debug("from segment encountered an error: %s", e)

        # Parse discharge datetime (PV1-45)
        discharge_str = segment.get_field_value(45)
        discharge_dt = None
        if discharge_str:
            try:
                if len(discharge_str) >= 14:
                    discharge_dt = datetime.strptime(discharge_str[:14], "%Y%m%d%H%M%S")
                elif len(discharge_str) >= 8:
                    discharge_dt = datetime.strptime(discharge_str[:8], "%Y%m%d")
            except ValueError as e:
                logger.debug("from segment encountered an error: %s", e)

        return cls(
            set_id=segment.get_field_value(1),
            patient_class=segment.get_field_value(2),
            assigned_patient_location=segment.get_field_value(3),
            admission_type=segment.get_field_value(4),
            preadmit_number=segment.get_field_value(5),
            prior_patient_location=segment.get_field_value(6),
            attending_doctor=segment.get_field_value(7),
            referring_doctor=segment.get_field_value(8),
            consulting_doctor=segment.get_field_value(9),
            hospital_service=segment.get_field_value(10),
            visit_number=segment.get_field_value(19),
            admit_datetime=admit_dt,
            discharge_datetime=discharge_dt,
        )


@dataclass
class OBXSegment:
    """Observation/Result segment."""

    set_id: str = ""
    value_type: str = ""  # OBX-2 (NM, ST, TX, CE, etc.)
    observation_identifier: str = ""  # OBX-3
    observation_sub_id: str = ""  # OBX-4
    observation_value: str = ""  # OBX-5
    units: str = ""  # OBX-6
    references_range: str = ""  # OBX-7
    abnormal_flags: str = ""  # OBX-8
    probability: str = ""  # OBX-9
    nature_of_abnormal_test: str = ""  # OBX-10
    observation_result_status: str = ""  # OBX-11
    effective_date: datetime | None = None  # OBX-12
    user_defined_access_checks: str = ""  # OBX-13
    datetime_of_observation: datetime | None = None  # OBX-14
    producers_id: str = ""  # OBX-15
    responsible_observer: str = ""  # OBX-16
    observation_method: str = ""  # OBX-17

    @classmethod
    def from_segment(cls, segment: HL7Segment) -> OBXSegment:
        """Create OBX from parsed segment."""
        # Parse observation datetime (OBX-14)
        obs_str = segment.get_field_value(14)
        obs_dt = None
        if obs_str:
            try:
                if len(obs_str) >= 14:
                    obs_dt = datetime.strptime(obs_str[:14], "%Y%m%d%H%M%S")
                elif len(obs_str) >= 8:
                    obs_dt = datetime.strptime(obs_str[:8], "%Y%m%d")
            except ValueError as e:
                logger.debug("from segment encountered an error: %s", e)

        return cls(
            set_id=segment.get_field_value(1),
            value_type=segment.get_field_value(2),
            observation_identifier=segment.get_field_value(3),
            observation_sub_id=segment.get_field_value(4),
            observation_value=segment.get_field_value(5),
            units=segment.get_field_value(6),
            references_range=segment.get_field_value(7),
            abnormal_flags=segment.get_field_value(8),
            probability=segment.get_field_value(9),
            nature_of_abnormal_test=segment.get_field_value(10),
            observation_result_status=segment.get_field_value(11),
            user_defined_access_checks=segment.get_field_value(13),
            datetime_of_observation=obs_dt,
            producers_id=segment.get_field_value(15),
            responsible_observer=segment.get_field_value(16),
            observation_method=segment.get_field_value(17),
        )


@dataclass
class ORCSegment:
    """Common Order segment."""

    order_control: str = ""  # ORC-1 (NW=new, CA=cancel, etc.)
    placer_order_number: str = ""  # ORC-2
    filler_order_number: str = ""  # ORC-3
    placer_group_number: str = ""  # ORC-4
    order_status: str = ""  # ORC-5
    response_flag: str = ""  # ORC-6
    quantity_timing: str = ""  # ORC-7
    parent: str = ""  # ORC-8
    datetime_of_transaction: datetime | None = None  # ORC-9
    entered_by: str = ""  # ORC-10
    verified_by: str = ""  # ORC-11
    ordering_provider: str = ""  # ORC-12

    @classmethod
    def from_segment(cls, segment: HL7Segment) -> ORCSegment:
        """Create ORC from parsed segment."""
        # Parse transaction datetime (ORC-9)
        dt_str = segment.get_field_value(9)
        dt = None
        if dt_str:
            try:
                if len(dt_str) >= 14:
                    dt = datetime.strptime(dt_str[:14], "%Y%m%d%H%M%S")
                elif len(dt_str) >= 8:
                    dt = datetime.strptime(dt_str[:8], "%Y%m%d")
            except ValueError as e:
                logger.debug("from segment encountered an error: %s", e)

        return cls(
            order_control=segment.get_field_value(1),
            placer_order_number=segment.get_field_value(2),
            filler_order_number=segment.get_field_value(3),
            placer_group_number=segment.get_field_value(4),
            order_status=segment.get_field_value(5),
            response_flag=segment.get_field_value(6),
            quantity_timing=segment.get_field_value(7),
            parent=segment.get_field_value(8),
            datetime_of_transaction=dt,
            entered_by=segment.get_field_value(10),
            verified_by=segment.get_field_value(11),
            ordering_provider=segment.get_field_value(12),
        )


@dataclass
class OBRSegment:
    """Observation Request segment."""

    set_id: str = ""
    placer_order_number: str = ""  # OBR-2
    filler_order_number: str = ""  # OBR-3
    universal_service_id: str = ""  # OBR-4
    priority: str = ""  # OBR-5
    requested_datetime: datetime | None = None  # OBR-6
    observation_datetime: datetime | None = None  # OBR-7
    observation_end_datetime: datetime | None = None  # OBR-8
    collection_volume: str = ""  # OBR-9
    collector_identifier: str = ""  # OBR-10
    specimen_action_code: str = ""  # OBR-11
    danger_code: str = ""  # OBR-12
    relevant_clinical_info: str = ""  # OBR-13
    specimen_received_datetime: datetime | None = None  # OBR-14
    specimen_source: str = ""  # OBR-15
    ordering_provider: str = ""  # OBR-16
    result_status: str = ""  # OBR-25

    @classmethod
    def from_segment(cls, segment: HL7Segment) -> OBRSegment:
        """Create OBR from parsed segment."""

        def parse_dt(val: str) -> datetime | None:
            if not val:
                return None
            try:
                if len(val) >= 14:
                    return datetime.strptime(val[:14], "%Y%m%d%H%M%S")
                elif len(val) >= 8:
                    return datetime.strptime(val[:8], "%Y%m%d")
            except ValueError as e:
                logger.debug("parse dt encountered an error: %s", e)
            return None

        return cls(
            set_id=segment.get_field_value(1),
            placer_order_number=segment.get_field_value(2),
            filler_order_number=segment.get_field_value(3),
            universal_service_id=segment.get_field_value(4),
            priority=segment.get_field_value(5),
            requested_datetime=parse_dt(segment.get_field_value(6)),
            observation_datetime=parse_dt(segment.get_field_value(7)),
            observation_end_datetime=parse_dt(segment.get_field_value(8)),
            collection_volume=segment.get_field_value(9),
            collector_identifier=segment.get_field_value(10),
            specimen_action_code=segment.get_field_value(11),
            danger_code=segment.get_field_value(12),
            relevant_clinical_info=segment.get_field_value(13),
            specimen_received_datetime=parse_dt(segment.get_field_value(14)),
            specimen_source=segment.get_field_value(15),
            ordering_provider=segment.get_field_value(16),
            result_status=segment.get_field_value(25),
        )


@dataclass
class SCHSegment:
    """Scheduling Activity segment."""

    placer_appointment_id: str = ""  # SCH-1
    filler_appointment_id: str = ""  # SCH-2
    occurrence_number: str = ""  # SCH-3
    placer_group_number: str = ""  # SCH-4
    schedule_id: str = ""  # SCH-5
    event_reason: str = ""  # SCH-6
    appointment_reason: str = ""  # SCH-7
    appointment_type: str = ""  # SCH-8
    appointment_duration: str = ""  # SCH-9
    appointment_duration_units: str = ""  # SCH-10
    appointment_timing_quantity: str = ""  # SCH-11
    placer_contact_person: str = ""  # SCH-12
    placer_contact_phone_number: str = ""  # SCH-13
    placer_contact_address: str = ""  # SCH-14
    placer_contact_location: str = ""  # SCH-15
    filler_contact_person: str = ""  # SCH-16
    filler_contact_phone_number: str = ""  # SCH-17
    filler_contact_address: str = ""  # SCH-18
    filler_contact_location: str = ""  # SCH-19
    entered_by_person: str = ""  # SCH-20
    entered_by_phone_number: str = ""  # SCH-21
    entered_by_location: str = ""  # SCH-22
    parent_placer_appointment_id: str = ""  # SCH-23
    parent_filler_appointment_id: str = ""  # SCH-24
    filler_status_code: str = ""  # SCH-25

    @classmethod
    def from_segment(cls, segment: HL7Segment) -> SCHSegment:
        """Create SCH from parsed segment."""
        return cls(
            placer_appointment_id=segment.get_field_value(1),
            filler_appointment_id=segment.get_field_value(2),
            occurrence_number=segment.get_field_value(3),
            placer_group_number=segment.get_field_value(4),
            schedule_id=segment.get_field_value(5),
            event_reason=segment.get_field_value(6),
            appointment_reason=segment.get_field_value(7),
            appointment_type=segment.get_field_value(8),
            appointment_duration=segment.get_field_value(9),
            appointment_duration_units=segment.get_field_value(10),
            appointment_timing_quantity=segment.get_field_value(11),
            placer_contact_person=segment.get_field_value(12),
            placer_contact_phone_number=segment.get_field_value(13),
            placer_contact_address=segment.get_field_value(14),
            placer_contact_location=segment.get_field_value(15),
            filler_contact_person=segment.get_field_value(16),
            filler_contact_phone_number=segment.get_field_value(17),
            filler_contact_address=segment.get_field_value(18),
            filler_contact_location=segment.get_field_value(19),
            entered_by_person=segment.get_field_value(20),
            entered_by_phone_number=segment.get_field_value(21),
            entered_by_location=segment.get_field_value(22),
            parent_placer_appointment_id=segment.get_field_value(23),
            parent_filler_appointment_id=segment.get_field_value(24),
            filler_status_code=segment.get_field_value(25),
        )


# =============================================================================
# HL7 Message
# =============================================================================


@dataclass
class HL7Message:
    """Complete HL7 v2 message."""

    raw: str
    segments: list[HL7Segment] = field(default_factory=list)

    # Typed segments (populated after parsing)
    msh: MSHSegment | None = None
    pid: PIDSegment | None = None
    pv1: PV1Segment | None = None
    obx_list: list[OBXSegment] = field(default_factory=list)
    orc: ORCSegment | None = None
    obr: OBRSegment | None = None
    sch: SCHSegment | None = None

    @property
    def message_type(self) -> str:
        """Get message type (e.g., 'ADT^A01')."""
        return self.msh.message_type if self.msh else ""

    @property
    def message_control_id(self) -> str:
        """Get message control ID."""
        return self.msh.message_control_id if self.msh else ""

    @property
    def patient_id(self) -> str:
        """Get primary patient identifier."""
        if self.pid and self.pid.patient_identifier_list:
            return self.pid.patient_identifier_list[0]
        return ""

    def get_segments(self, segment_type: str) -> list[HL7Segment]:
        """Get all segments of a given type."""
        return [s for s in self.segments if s.segment_type == segment_type]


# =============================================================================
# HL7 Parser
# =============================================================================


class HL7Parser:
    """
    Parser for HL7 v2.x messages.

    Handles pipe-delimited segment format with proper encoding
    character support.
    """

    def __init__(
        self,
        strict: bool = False,
        default_version: str = "2.5.1",
    ):
        """
        Initialize parser.

        Args:
            strict: If True, raise on parsing errors. If False, skip bad segments.
            default_version: Default HL7 version if not specified in message.
        """
        self.strict = strict
        self.default_version = default_version

    def parse(self, raw: str) -> HL7Message:
        """
        Parse an HL7 v2 message.

        Args:
            raw: Raw HL7 message string (segments separated by CR or CRLF)

        Returns:
            Parsed HL7Message

        Raises:
            ValueError: If message is invalid and strict mode is enabled
        """
        # Normalize line endings
        normalized = raw.replace("\r\n", "\r").replace("\n", "\r")

        # Split into segment lines
        lines = [line.strip() for line in normalized.split("\r") if line.strip()]

        if not lines:
            raise ValueError("Empty HL7 message")

        # First segment must be MSH
        if not lines[0].startswith("MSH"):
            raise ValueError("HL7 message must start with MSH segment")

        # Detect encoding characters from MSH
        msh_line = lines[0]
        if len(msh_line) < 8:
            raise ValueError("MSH segment too short")

        field_sep = msh_line[3]  # Character after 'MSH'
        encoding_chars = msh_line[4:8]  # Next 4 characters

        # Parse all segments
        segments: list[HL7Segment] = []
        for line in lines:
            try:
                segment = HL7Segment.parse(line, field_sep, encoding_chars)
                segments.append(segment)
            except (ValueError, IndexError) as e:
                if self.strict:
                    raise ValueError(f"Failed to parse segment: {line}") from e
                logger.warning("Skipping invalid segment: %s (%s)", line, e)

        # Build message with typed segments
        message = HL7Message(raw=raw, segments=segments)
        self._populate_typed_segments(message)

        return message

    def _populate_typed_segments(self, message: HL7Message) -> None:
        """Populate typed segment objects from parsed segments."""
        for segment in message.segments:
            try:
                if segment.segment_type == "MSH":
                    message.msh = MSHSegment.from_segment(segment)
                elif segment.segment_type == "PID":
                    message.pid = PIDSegment.from_segment(segment)
                elif segment.segment_type == "PV1":
                    message.pv1 = PV1Segment.from_segment(segment)
                elif segment.segment_type == "OBX":
                    message.obx_list.append(OBXSegment.from_segment(segment))
                elif segment.segment_type == "ORC":
                    message.orc = ORCSegment.from_segment(segment)
                elif segment.segment_type == "OBR":
                    message.obr = OBRSegment.from_segment(segment)
                elif segment.segment_type == "SCH":
                    message.sch = SCHSegment.from_segment(segment)
            except (ValueError, KeyError, IndexError, AttributeError) as e:
                if self.strict:
                    raise
                logger.warning("Failed to parse typed segment %s: %s", segment.segment_type, e)

    def parse_mllp(self, data: bytes) -> list[HL7Message]:
        """
        Parse MLLP-framed HL7 messages.

        MLLP format: <VT>message<FS><CR>

        Args:
            data: Raw MLLP data

        Returns:
            List of parsed HL7 messages
        """
        messages: list[HL7Message] = []

        # Split on MLLP delimiters
        # Format: 0x0B <message> 0x1C 0x0D
        parts = data.split(MLLP_END_BLOCK + MLLP_CARRIAGE_RETURN)

        for part in parts:
            # Remove start block
            if part.startswith(MLLP_START_BLOCK):
                part = part[1:]

            if not part.strip():
                continue

            try:
                # Decode as UTF-8 (or ASCII, which is subset)
                raw = part.decode("utf-8", errors="replace")
                messages.append(self.parse(raw))
            except (ValueError, UnicodeDecodeError) as e:
                if self.strict:
                    raise
                logger.warning("Failed to parse MLLP message: %s", e)

        return messages

    def encode_mllp(self, message: HL7Message) -> bytes:
        """
        Encode an HL7 message with MLLP framing.

        Args:
            message: HL7 message to encode

        Returns:
            MLLP-framed bytes
        """
        raw_bytes = message.raw.encode("utf-8")
        return MLLP_START_BLOCK + raw_bytes + MLLP_END_BLOCK + MLLP_CARRIAGE_RETURN


# =============================================================================
# PHI Redaction (HL7-specific)
# =============================================================================


@dataclass
class HL7RedactionResult:
    """Result of HL7 PHI redaction."""

    original_hash: str  # SHA-256 of original for audit
    redacted_message: str
    redactions_count: int
    redacted_fields: list[str]  # List of field paths that were redacted


class HL7PHIRedactor:
    """
    PHI redactor for HL7 v2 messages using Safe Harbor method.

    Targets specific HL7 fields known to contain PHI per HIPAA guidelines.
    """

    # Fields containing PHI (segment-field format)
    PHI_FIELDS = {
        # PID segment - Patient demographics
        "PID-3": "patient_identifiers",  # Patient ID list
        "PID-5": "patient_name",
        "PID-6": "mothers_maiden_name",
        "PID-7": "date_of_birth",
        "PID-9": "patient_alias",
        "PID-11": "patient_address",
        "PID-13": "phone_home",
        "PID-14": "phone_business",
        "PID-18": "patient_account_number",
        "PID-19": "ssn",
        # NK1 segment - Next of Kin
        "NK1-2": "nok_name",
        "NK1-4": "nok_address",
        "NK1-5": "nok_phone",
        "NK1-6": "nok_business_phone",
        # GT1 segment - Guarantor
        "GT1-3": "guarantor_name",
        "GT1-5": "guarantor_address",
        "GT1-6": "guarantor_phone_home",
        "GT1-7": "guarantor_phone_business",
        "GT1-12": "guarantor_ssn",
        # IN1 segment - Insurance
        "IN1-16": "insured_name",
        "IN1-18": "insured_dob",
        "IN1-19": "insured_address",
    }

    # Regex patterns for PHI detection in free text (e.g., NTE segments)
    TEXT_PATTERNS = {
        "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "phone": re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        "mrn": re.compile(r"\b(?:MRN|Medical Record)[:\s#]*[\w-]+\b", re.IGNORECASE),
        "date_full": re.compile(
            r"\b(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b"
        ),
        "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    }

    def __init__(
        self,
        redact_dates: bool = True,
        preserve_year: bool = True,
        redact_free_text: bool = True,
    ):
        """
        Initialize PHI redactor.

        Args:
            redact_dates: Whether to redact date fields
            preserve_year: If True, keep year in redacted dates for clinical relevance
            redact_free_text: Whether to scan and redact PHI in free text fields
        """
        self.redact_dates = redact_dates
        self.preserve_year = preserve_year
        self.redact_free_text = redact_free_text

    def redact(self, message: HL7Message) -> HL7RedactionResult:
        """
        Redact PHI from an HL7 message.

        Args:
            message: Parsed HL7 message

        Returns:
            Redaction result with redacted message text
        """
        original_hash = hashlib.sha256(message.raw.encode()).hexdigest()
        redacted_fields: list[str] = []
        redactions_count = 0

        # Work with raw message lines
        lines = message.raw.replace("\r\n", "\r").replace("\n", "\r").split("\r")
        redacted_lines: list[str] = []

        for line in lines:
            if not line.strip():
                redacted_lines.append(line)
                continue

            # Get segment type
            sep_idx = line.find("|")
            if sep_idx == -1:
                redacted_lines.append(line)
                continue

            segment_type = line[:sep_idx] if sep_idx > 0 else line[:3]

            # Handle MSH specially (field separator position)
            if segment_type == "MSH":
                segment_type = "MSH"

            # Redact known PHI fields
            redacted_line, field_redactions = self._redact_segment_fields(line, segment_type)
            redacted_fields.extend(field_redactions)
            redactions_count += len(field_redactions)

            # Redact free text in NTE segments
            if self.redact_free_text and segment_type == "NTE":
                redacted_line, text_redactions = self._redact_free_text(redacted_line)
                redactions_count += text_redactions

            redacted_lines.append(redacted_line)

        redacted_message = "\r".join(redacted_lines)

        return HL7RedactionResult(
            original_hash=original_hash,
            redacted_message=redacted_message,
            redactions_count=redactions_count,
            redacted_fields=redacted_fields,
        )

    def _redact_segment_fields(self, line: str, segment_type: str) -> tuple[str, list[str]]:
        """Redact specific fields in a segment line."""
        redacted_fields: list[str] = []

        # Find field separator (first char after segment ID)
        if segment_type == "MSH":
            field_sep = line[3] if len(line) > 3 else "|"
            # For MSH, fields start at position 4
            parts = [line[:3], field_sep] + line[4:].split(field_sep)
        else:
            field_sep = "|"
            parts = line.split(field_sep)

        # Check each field against PHI list
        modified = False
        for field_num in range(len(parts)):
            field_key = f"{segment_type}-{field_num}"

            if field_key in self.PHI_FIELDS:
                phi_type = self.PHI_FIELDS[field_key]

                # Handle date fields specially
                if phi_type == "date_of_birth" and self.preserve_year:
                    original = parts[field_num]
                    if len(original) >= 4:
                        # Keep year, redact rest
                        parts[field_num] = original[:4] + "0101"
                        if parts[field_num] != original:
                            redacted_fields.append(f"{field_key}:{phi_type}")
                            modified = True
                else:
                    if parts[field_num]:
                        parts[field_num] = f"[REDACTED-{phi_type.upper()}]"
                        redacted_fields.append(f"{field_key}:{phi_type}")
                        modified = True

        if modified:
            if segment_type == "MSH":
                # Reconstruct MSH with proper structure
                line = parts[0] + parts[1] + field_sep.join(parts[2:])
            else:
                line = field_sep.join(parts)

        return line, redacted_fields

    def _redact_free_text(self, line: str) -> tuple[str, int]:
        """Redact PHI patterns in free text."""
        redactions = 0
        redacted = line

        for phi_type, pattern in self.TEXT_PATTERNS.items():
            matches = pattern.findall(redacted)
            if matches:
                redactions += len(matches)
                redacted = pattern.sub(f"[REDACTED-{phi_type.upper()}]", redacted)

        return redacted, redactions


# =============================================================================
# HL7 v2 Connector
# =============================================================================


class HL7v2Connector(EnterpriseConnector):
    """
    Enterprise connector for HL7 v2.x healthcare data.

    Supports multiple source types:
    - TCP/MLLP listener
    - File-based polling (filesystem or SFTP)
    - HTTP webhook receiver

    Features:
    - HIPAA-compliant PHI redaction
    - Message type filtering
    - Audit logging for compliance
    """

    name = "HL7 v2.x Healthcare Connector"

    @property
    def source_type(self) -> SourceType:
        """Return source type for this connector."""
        return SourceType.DATABASE

    def __init__(
        self,
        connector_id: str,
        tenant_id: str = "default",
        # Source configuration
        source_type: str = "file",  # "file", "mllp", "http"
        source_path: str | None = None,  # For file source
        mllp_host: str = "0.0.0.0",  # MLLP listener binds all interfaces by default
        mllp_port: int = 2575,
        # Message filtering
        message_types: list[str] | None = None,  # Filter by type (e.g., ["ADT", "ORU"])
        # PHI handling
        enable_phi_redaction: bool = True,
        redact_dates: bool = True,
        preserve_year: bool = True,
        # Processing
        strict_parsing: bool = False,
        # Audit
        enable_audit_log: bool = True,
        audit_log_path: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(connector_id=connector_id, tenant_id=tenant_id, **kwargs)

        self.hl7_source_type = source_type
        self.source_path = source_path
        self.mllp_host = mllp_host
        self.mllp_port = mllp_port
        self.message_types = set(message_types) if message_types else None
        self.enable_phi_redaction = enable_phi_redaction
        self.strict_parsing = strict_parsing
        self.enable_audit_log = enable_audit_log
        self.audit_log_path = audit_log_path

        # Initialize parser and redactor
        self.parser = HL7Parser(strict=strict_parsing)
        self.redactor = (
            HL7PHIRedactor(
                redact_dates=redact_dates,
                preserve_year=preserve_year,
            )
            if enable_phi_redaction
            else None
        )

        # MLLP server state
        self._mllp_server: asyncio.AbstractServer | None = None
        self._message_queue: asyncio.Queue[HL7Message] = asyncio.Queue()

        # Statistics
        self._messages_processed = 0
        self._messages_redacted = 0
        self._parsing_errors = 0

    async def start_mllp_listener(self) -> None:
        """Start MLLP TCP listener for receiving HL7 messages."""
        if self._mllp_server is not None:
            logger.warning("MLLP listener already running")
            return

        async def handle_connection(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            """Handle incoming MLLP connection."""
            peer = writer.get_extra_info("peername")
            logger.info("HL7 MLLP connection from %s", peer)

            try:
                for _page in range(_MAX_PAGES):
                    # Read until we see the end of message marker
                    data = await reader.readuntil(MLLP_END_BLOCK + MLLP_CARRIAGE_RETURN)
                    if not data:
                        break

                    try:
                        messages: list[HL7Message] = []
                        messages = self.parser.parse_mllp(data)
                        for msg in messages:
                            await self._message_queue.put(msg)
                            logger.debug(
                                "Received HL7 message: %s (control_id=%s)",
                                msg.message_type,
                                msg.message_control_id,
                            )

                            # Send ACK
                            ack = self._create_ack(msg, "AA")  # Application Accept
                            writer.write(self.parser.encode_mllp(ack))
                            await writer.drain()

                    except (ValueError, UnicodeDecodeError) as e:
                        logger.error("Error processing MLLP message: %s", e)
                        self._parsing_errors += 1
                        # Send NACK
                        if messages:
                            nack = self._create_ack(messages[0], "AE")  # Application Error
                            writer.write(self.parser.encode_mllp(nack))
                            await writer.drain()

            except asyncio.IncompleteReadError:
                logger.debug("Client %s disconnected", peer)
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                logger.error("MLLP connection error: %s", e)
            finally:
                writer.close()
                await writer.wait_closed()

        self._mllp_server = await asyncio.start_server(
            handle_connection, self.mllp_host, self.mllp_port
        )

        logger.info("HL7 MLLP listener started on %s:%s", self.mllp_host, self.mllp_port)

    async def stop_mllp_listener(self) -> None:
        """Stop MLLP TCP listener."""
        if self._mllp_server is not None:
            self._mllp_server.close()
            await self._mllp_server.wait_closed()
            self._mllp_server = None
            logger.info("HL7 MLLP listener stopped")

    def _create_ack(self, original: HL7Message, ack_code: str) -> HL7Message:
        """Create an ACK message for the original message."""
        now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        # Build ACK message
        msh = original.msh
        ack_lines = [
            f"MSH|^~\\&|{msh.receiving_application if msh else ''}|"
            f"{msh.receiving_facility if msh else ''}|"
            f"{msh.sending_application if msh else ''}|"
            f"{msh.sending_facility if msh else ''}|"
            f"{now}||ACK|{now}|P|2.5.1",
            f"MSA|{ack_code}|{original.message_control_id}",
        ]

        ack_raw = "\r".join(ack_lines)
        return self.parser.parse(ack_raw)

    async def sync_items(
        self,
        state: SyncState | None = None,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """
        Sync HL7 messages from configured source.

        Yields SyncItems for each processed message.
        """
        if state is None:
            state = SyncState(connector_id=self.connector_id)
        if self.hl7_source_type == "mllp":
            # Process messages from queue (populated by MLLP listener)
            while not self._message_queue.empty():
                try:
                    message = self._message_queue.get_nowait()
                    item = await self._process_message(message)
                    if item:
                        yield item
                except asyncio.QueueEmpty:
                    break

        elif self.hl7_source_type == "file":
            # Process files from source path
            if not self.source_path:
                logger.error("No source_path configured for file-based sync")
                return

            from pathlib import Path

            source_dir = Path(self.source_path)
            if not source_dir.exists():
                logger.error("Source path does not exist: %s", self.source_path)
                return

            # Find HL7 files (common extensions)
            patterns = ["*.hl7", "*.HL7", "*.txt"]
            files: list[Path] = []
            for pattern in patterns:
                files.extend(source_dir.glob(pattern))

            # Sort by modification time for consistent ordering
            files.sort(key=lambda p: p.stat().st_mtime)

            for file_path in files:
                try:
                    raw = file_path.read_text(encoding="utf-8", errors="replace")
                    message = self.parser.parse(raw)
                    item = await self._process_message(message, source_file=str(file_path))
                    if item:
                        yield item

                except (ValueError, OSError, UnicodeDecodeError) as e:
                    logger.error("Error processing file %s: %s", file_path, e)
                    self._parsing_errors += 1

    async def _process_message(
        self,
        message: HL7Message,
        source_file: str | None = None,
    ) -> SyncItem | None:
        """Process a single HL7 message into a SyncItem."""
        # Check message type filter
        if self.message_types:
            msg_type = message.message_type.split("^")[0] if message.message_type else ""
            if msg_type not in self.message_types:
                logger.debug("Skipping message type %s", message.message_type)
                return None

        self._messages_processed += 1

        # Apply PHI redaction
        content = message.raw
        redaction_result = None
        if self.redactor:
            redaction_result = self.redactor.redact(message)
            content = redaction_result.redacted_message
            self._messages_redacted += 1

        # Build metadata
        metadata: dict[str, Any] = {
            "message_type": message.message_type,
            "message_control_id": message.message_control_id,
            "hl7_version": message.msh.version_id if message.msh else "unknown",
            "sending_application": message.msh.sending_application if message.msh else "",
            "sending_facility": message.msh.sending_facility if message.msh else "",
        }

        if source_file:
            metadata["source_file"] = source_file

        if redaction_result:
            metadata["phi_redacted"] = True
            metadata["redactions_count"] = redaction_result.redactions_count
            metadata["original_hash"] = redaction_result.original_hash

        # Extract clinical context for title
        title = f"HL7 {message.message_type}"
        if message.pid:
            title = f"{title} - Patient Visit"
        if message.obr:
            title = f"{title} - {message.obr.universal_service_id}"

        # Log audit event
        if self.enable_audit_log:
            self._log_audit_event(message, redaction_result)

        return SyncItem(
            id=message.message_control_id or hashlib.sha256(content.encode()).hexdigest()[:16],
            content=content,
            source_type="hl7v2",
            source_id=f"hl7://{message.msh.sending_facility if message.msh else 'unknown'}/"
            f"{message.message_control_id}",
            title=title,
            created_at=message.msh.message_datetime if message.msh else None,
            domain="healthcare",
            confidence=0.9 if not self.strict_parsing else 0.95,
            metadata=metadata,
        )

    def _log_audit_event(
        self,
        message: HL7Message,
        redaction_result: HL7RedactionResult | None,
    ) -> None:
        """Log audit event for compliance."""
        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "hl7_message_processed",
            "connector_id": self.connector_id,
            "tenant_id": self.tenant_id,
            "message_type": message.message_type,
            "message_control_id": message.message_control_id,
            "sending_facility": message.msh.sending_facility if message.msh else None,
            "phi_redacted": redaction_result is not None,
            "redactions_count": redaction_result.redactions_count if redaction_result else 0,
        }

        logger.info("AUDIT: %s", audit_entry)

        # Write to audit file if configured
        if self.audit_log_path:
            try:
                import json

                with open(self.audit_log_path, "a") as f:
                    f.write(json.dumps(audit_entry) + "\n")
            except OSError as e:
                logger.error("Failed to write audit log: %s", e)

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs: Any,
    ) -> list[Evidence]:
        """Search processed HL7 messages (placeholder for Knowledge Mound integration)."""
        # This would typically query the Knowledge Mound
        logger.warning("HL7v2Connector.search() requires Knowledge Mound integration")
        return []

    async def fetch(
        self,
        evidence_id: str,
    ) -> Evidence | None:
        """Fetch a specific HL7 message by ID (placeholder for Knowledge Mound integration)."""
        logger.warning("HL7v2Connector.fetch() requires Knowledge Mound integration")
        return None

    def get_stats(self) -> dict[str, Any]:
        """Get connector statistics."""
        return {
            "messages_processed": self._messages_processed,
            "messages_redacted": self._messages_redacted,
            "parsing_errors": self._parsing_errors,
            "source_type": self.hl7_source_type,
            "phi_redaction_enabled": self.enable_phi_redaction,
            "message_type_filter": list(self.message_types) if self.message_types else None,
        }

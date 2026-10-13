"""
OpenAPI endpoint definitions for Device Integrations.

Endpoints for IoT and voice assistant device integrations
including Alexa, Google Home, and Apple HomeKit.
"""

from aragora.server.openapi.helpers import (
    _ok_response,
    _array_response,
    STANDARD_ERRORS,
)

DEVICES_ENDPOINTS = {
    "/api/devices/register": {
        "post": {
            "tags": ["Devices"],
            "summary": "Register a device",
            "description": """Register a new device for Aragora integration.

**Supported device types:**
- alexa: Amazon Alexa devices
- google_home: Google Home/Nest devices
- apple_homekit: Apple HomeKit devices
- custom: Custom IoT devices

**Returns:** Device ID and authentication token for the device.""",
            "operationId": "registerDevice",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["type", "name"],
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["alexa", "google_home", "apple_homekit", "custom"],
                                },
                                "name": {"type": "string"},
                                "capabilities": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "metadata": {"type": "object"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "201": _ok_response(
                    "Device registered",
                    {
                        "device_id": {"type": "string"},
                        "token": {"type": "string"},
                        "expires_at": {"type": "string", "format": "date-time"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/devices": {
        "get": {
            "tags": ["Devices"],
            "summary": "List registered devices",
            "description": "Returns all devices registered to the current user/workspace.",
            "operationId": "listDevices",
            "responses": {
                "200": _array_response(
                    "Registered devices",
                    {
                        "device_id": {"type": "string"},
                        "type": {"type": "string"},
                        "name": {"type": "string"},
                        "status": {"type": "string"},
                        "last_seen": {"type": "string", "format": "date-time"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/devices/{device_id}": {
        "get": {
            "tags": ["Devices"],
            "summary": "Get device details",
            "description": """Retrieve detailed information about a specific registered device.

**Response includes:**
- Device type (alexa, google_home, apple_homekit, custom)
- Device name and capabilities
- Connection status and metadata
- Last seen timestamp

**Use cases:**
- Check device configuration
- Verify device capabilities
- Debug connection issues""",
            "operationId": "getDevice",
            "parameters": [
                {
                    "name": "device_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Device details",
                    {
                        "device_id": {"type": "string"},
                        "type": {"type": "string"},
                        "name": {"type": "string"},
                        "capabilities": {"type": "array", "items": {"type": "string"}},
                        "status": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
            },
            "security": [{"bearerAuth": []}],
        },
        "delete": {
            "tags": ["Devices"],
            "summary": "Unregister a device",
            "description": """Remove a device from Aragora integration.

**Actions:**
- Revokes the device authentication token
- Removes device from registered devices list
- Cleans up any device-specific data

**Note:** This action cannot be undone. The device will need to be re-registered to use Aragora again.""",
            "operationId": "unregisterDevice",
            "parameters": [
                {
                    "name": "device_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response("Device unregistered", {"success": {"type": "boolean"}}),
                "404": STANDARD_ERRORS["404"],
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/devices/health": {
        "get": {
            "tags": ["Devices"],
            "summary": "Get device integration health",
            "description": "Returns health status for all device integration services.",
            "operationId": "getDeviceHealth",
            "responses": {
                "200": _ok_response(
                    "Device integration health",
                    {
                        "alexa": {"type": "object"},
                        "google_home": {"type": "object"},
                        "apple_homekit": {"type": "object"},
                        "overall_status": {"type": "string"},
                    },
                ),
            },
            "security": [{"bearerAuth": []}],
        },
    },
    # Alexa-specific endpoints
    "/api/devices/alexa/webhook": {
        "post": {
            "tags": ["Devices", "Alexa"],
            "summary": "Handle Alexa skill request",
            "description": """Webhook endpoint for Alexa Smart Home or Custom Skills.

**Request types:**
- LaunchRequest: Skill opened
- IntentRequest: User intent
- SessionEndedRequest: Session closed

**Signature:** Alexa includes signature headers for request verification.""",
            "operationId": "handleAlexaWebhook",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "version": {"type": "string"},
                                "session": {"type": "object"},
                                "request": {"type": "object"},
                                "context": {"type": "object"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response(
                    "Alexa response",
                    {
                        "version": {"type": "string"},
                        "response": {"type": "object"},
                        "sessionAttributes": {"type": "object"},
                    },
                ),
            },
        },
    },
    # Google Home endpoints
    "/api/devices/google/webhook": {
        "post": {
            "tags": ["Devices", "Google Home"],
            "summary": "Handle Google Actions request",
            "description": """Webhook endpoint for Google Actions/Dialogflow.

**Intents:**
- actions.intent.MAIN: Launch action
- Custom intents: User-defined intents

**Fulfillment:** Returns response for Google Assistant.""",
            "operationId": "handleGoogleWebhook",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "handler": {"type": "object"},
                                "intent": {"type": "object"},
                                "scene": {"type": "object"},
                                "session": {"type": "object"},
                                "user": {"type": "object"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response(
                    "Google Actions response",
                    {
                        "prompt": {"type": "object"},
                        "scene": {"type": "object"},
                        "session": {"type": "object"},
                    },
                ),
            },
        },
    },
}

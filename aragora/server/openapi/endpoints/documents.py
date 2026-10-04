"""Document and media endpoint definitions."""

from aragora.server.openapi.helpers import STANDARD_ERRORS, _ok_response

DOCUMENT_ENDPOINTS = {
    "/api/documents": {
        "get": {
            "tags": ["Documents"],
            "summary": "List documents",
            "description": (
                "Get list of uploaded documents available for debate context. Lists only "
                "documents owned by the caller's organization; requires a signed-in user "
                "with an organization."
            ),
            "operationId": "listDocuments",
            "responses": {
                "200": _ok_response(
                    "Document list",
                    {
                        "documents": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "filename": {"type": "string"},
                                    "size_bytes": {"type": "integer"},
                                    "mime_type": {"type": "string"},
                                    "uploaded_at": {"type": "string", "format": "date-time"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/documents/formats": {
        "get": {
            "tags": ["Documents"],
            "summary": "Supported formats",
            "description": "Get list of supported document formats for upload.",
            "operationId": "listDocumentsFormats",
            "responses": {
                "200": _ok_response(
                    "Supported formats",
                    {
                        "formats": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                )
            },
        },
    },
    "/api/documents/upload": {
        "post": {
            "tags": ["Documents"],
            "summary": "Upload document",
            "description": (
                "Upload a document to be used as context in debates, as multipart/form-data "
                "or as a raw body named by the X-Filename header. The document is owned by "
                "the caller's organization; requires a signed-in user with an organization."
            ),
            "operationId": "createDocumentsUpload",
            "requestBody": {
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "file": {
                                    "type": "string",
                                    "format": "binary",
                                    "description": "Document file to upload",
                                },
                                "filename": {"type": "string", "description": "Override filename"},
                                "content_type": {"type": "string", "description": "MIME type"},
                            },
                            "required": ["file"],
                        }
                    }
                }
            },
            "responses": {
                "201": _ok_response(
                    "Document uploaded",
                    {
                        "id": {"type": "string"},
                        "filename": {"type": "string"},
                        "size_bytes": {"type": "integer"},
                        "status": {"type": "string"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/podcast/feed.xml": {
        "get": {
            "tags": ["Media"],
            "summary": "Podcast RSS feed",
            "description": "Get RSS feed for debate podcast episodes.",
            "operationId": "listPodcastFeed.Xml",
            "responses": {"200": {"description": "RSS feed", "content": {"application/xml": {}}}},
        },
    },
    "/api/podcast/episodes": {
        "get": {
            "tags": ["Media"],
            "summary": "Podcast episodes",
            "description": "Get list of available podcast episodes from debates.",
            "operationId": "listPodcastEpisodes",
            "responses": {
                "200": _ok_response(
                    "Episode list",
                    {
                        "episodes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "debate_id": {"type": "string"},
                                    "duration_seconds": {"type": "integer"},
                                    "audio_url": {"type": "string"},
                                    "published_at": {"type": "string", "format": "date-time"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                    },
                )
            },
        },
    },
    "/api/youtube/auth": {
        "get": {
            "tags": ["Social"],
            "summary": "YouTube auth URL",
            "description": "Get OAuth authorization URL for YouTube integration.",
            "operationId": "listYoutubeAuth",
            "responses": {
                "200": _ok_response(
                    "Auth URL",
                    {
                        "url": {"type": "string"},
                        "state": {"type": "string"},
                    },
                )
            },
        },
    },
    "/api/youtube/callback": {
        "get": {
            "tags": ["Social"],
            "summary": "YouTube OAuth callback",
            "description": "Handle OAuth callback from YouTube authorization.",
            "operationId": "listYoutubeCallback",
            "responses": {
                "200": _ok_response(
                    "Auth complete",
                    {
                        "success": {"type": "boolean"},
                        "message": {"type": "string"},
                    },
                )
            },
        },
    },
    "/api/youtube/status": {
        "get": {
            "tags": ["Social"],
            "summary": "YouTube auth status",
            "description": "Check current YouTube authorization status.",
            "operationId": "listYoutubeStatus",
            "responses": {
                "200": _ok_response(
                    "Auth status",
                    {
                        "connected": {"type": "boolean"},
                        "channel_id": {"type": "string"},
                        "channel_name": {"type": "string"},
                    },
                )
            },
        },
    },
}

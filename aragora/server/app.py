"""
Aragora FastAPI Application Entry Point.

This module provides the main FastAPI application that can be run alongside
the existing ThreadingHTTPServer for gradual migration to async.

Usage:
    # Run with uvicorn
    uvicorn aragora.server.app:app --host 0.0.0.0 --port 8081

    # Or with reload for development
    uvicorn aragora.server.app:app --reload --port 8081

    # Run alongside legacy server (different ports)
    # Full API + WS: aragora serve --api-port 8080 --ws-port 8765
    # FastAPI: uvicorn aragora.server.app:app --port 8081

The FastAPI server exposes:
    - /api/v2/* - New async endpoints
    - /healthz, /readyz - K8s probes
    - /api/v2/docs - OpenAPI documentation
"""

from aragora.server.fastapi import create_app

# Create the FastAPI application
app = create_app()

# Convenience alias for running with "python -m aragora.server.app"
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "aragora.server.app:app",
        host="0.0.0.0",  # dev server binds all interfaces
        port=8081,
        reload=True,
    )

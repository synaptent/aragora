"""Handler utilities module.

Provides reusable utilities for HTTP handlers including:
- Rate limiting (token bucket algorithm)
- Query parameter extraction and validation
- URL routing and pattern matching
- Database connection helpers
- Safe data access utilities
- Handler decorators (auth, validation, error handling)
- Lazy store initialization (LazyStoreFactory)
- Safe data fetching with error handling (safe_fetch_with_fallback)
- Authentication mixins (SecureEndpointMixin)
"""

from .database import get_db_connection, table_exists
from .lazy_stores import LazyStoreFactory, LazyStoreRegistry
from .safe_fetch import (
    safe_fetch as safe_fetch_with_fallback,
    safe_fetch_async,
    SafeFetchContext,
    fetch_multiple,
    fetch_multiple_async,
)
from .auth import (
    ForbiddenError,
    UnauthorizedError,
    get_auth_context,
    require_authenticated,
)
from .auth_mixins import (
    SecureEndpointMixin,
    AuthenticatedHandlerMixin,
    require_permission as require_permission_mixin,
    require_any_permission,
    require_all_permissions,
)
from .decorators import (
    PERMISSION_MATRIX,
    auto_error_response,
    generate_trace_id,
    handle_errors,
    has_permission,
    log_request,
    map_exception_to_status,
    require_auth,
    require_feature,
    require_permission,
    require_storage,
    require_user_auth,
    safe_fetch,
    validate_params,
    with_error_recovery,
)
from .params import (
    get_bool_param,
    get_bounded_float_param,
    get_bounded_string_param,
    get_clamped_int_param,
    get_float_param,
    get_int_param,
    get_string_param,
    parse_query_params,
)
from .rate_limit import RateLimiter, get_client_ip, get_exact_client_ip, rate_limit
from .aiohttp_responses import web_error_response
from .responses import (
    HandlerResult,
    error_response,
    html_response,
    json_response,
    normalize_pagination_response,
    paginated_response,
    parse_pagination_params,
    redirect_response,
)
from .routing import PathMatcher, RouteDispatcher
from .safe_data import safe_get, safe_get_nested, safe_json_parse
from .json_body import parse_json_body, parse_json_body_allow_array
from .sanitization import (
    RESPONSE_SENSITIVE_FIELDS,
    sanitize_response,
    sanitize_user_response,
    sanitize_integration_response,
    sanitize_payment_response,
    sanitize_output,
)
from .rbac_guard import (
    rbac_available,
    rbac_fail_closed,
    is_production_env,
)
from .file_validation import (
    validate_file_upload,
    validate_file_size,
    validate_mime_type,
    validate_extension,
    validate_filename_security,
    sanitize_filename,
    get_max_file_size,
    get_max_file_size_mb,
    FileValidationResult,
    FileValidationError,
    FileValidationErrorCode,
    ALLOWED_MIME_TYPES,
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    MAX_FILENAME_LENGTH,
)

__all__ = [
    # Rate limiting
    "RateLimiter",
    "rate_limit",
    "get_client_ip",
    "get_exact_client_ip",
    # Parameter extraction
    "parse_query_params",
    "get_int_param",
    "get_float_param",
    "get_bool_param",
    "get_string_param",
    "get_clamped_int_param",
    "get_bounded_float_param",
    "get_bounded_string_param",
    # Routing
    "PathMatcher",
    "RouteDispatcher",
    # Database
    "get_db_connection",
    "table_exists",
    # Safe data access
    "safe_get",
    "safe_get_nested",
    "safe_json_parse",
    # Response builders
    "HandlerResult",
    "json_response",
    "error_response",
    "html_response",
    "redirect_response",
    "web_error_response",
    # Pagination helpers
    "paginated_response",
    "parse_pagination_params",
    "normalize_pagination_response",
    # Decorators
    "generate_trace_id",
    "map_exception_to_status",
    "validate_params",
    "handle_errors",
    "auto_error_response",
    "log_request",
    "PERMISSION_MATRIX",
    "has_permission",
    "require_permission",
    "require_user_auth",
    "require_auth",
    "require_storage",
    "require_feature",
    "safe_fetch",
    "with_error_recovery",
    # Lazy store initialization (new)
    "LazyStoreFactory",
    "LazyStoreRegistry",
    # Safe fetching with fallback (new)
    "safe_fetch_with_fallback",
    "safe_fetch_async",
    "SafeFetchContext",
    "fetch_multiple",
    "fetch_multiple_async",
    # Auth mixins (new)
    "SecureEndpointMixin",
    "AuthenticatedHandlerMixin",
    "require_permission_mixin",
    "require_any_permission",
    "require_all_permissions",
    # Response sanitization
    "RESPONSE_SENSITIVE_FIELDS",
    "sanitize_response",
    "sanitize_user_response",
    "sanitize_integration_response",
    "sanitize_payment_response",
    "sanitize_output",
    # Auth exceptions and utilities (canonical exports)
    "ForbiddenError",
    "UnauthorizedError",
    "get_auth_context",
    "require_authenticated",
    # JSON body parsing
    "parse_json_body",
    "parse_json_body_allow_array",
    # File validation
    "validate_file_upload",
    "validate_file_size",
    "validate_mime_type",
    "validate_extension",
    "validate_filename_security",
    "sanitize_filename",
    "get_max_file_size",
    "get_max_file_size_mb",
    "FileValidationResult",
    "FileValidationError",
    "FileValidationErrorCode",
    "ALLOWED_MIME_TYPES",
    "ALLOWED_EXTENSIONS",
    "MAX_FILE_SIZE",
    "MAX_FILENAME_LENGTH",
    # RBAC import guard (fail-closed in production)
    "rbac_available",
    "rbac_fail_closed",
    "is_production_env",
]

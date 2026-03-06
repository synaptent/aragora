"""
Inbox Management Handlers.

API handlers for inbox intelligence features:
- Action item extraction and tracking
- Meeting detection and calendar integration
- Email categorization
- Priority scoring
- Email actions (send, archive, snooze, etc.)
"""

from .action_items import (
    get_action_items_handlers,
    handle_auto_snooze_meeting,
    handle_batch_extract,
    handle_complete_action,
    handle_detect_meeting,
    handle_extract_action_items,
    handle_get_due_soon,
    handle_list_pending_actions,
    handle_update_action_status,
)

from .email_actions import (
    get_email_actions_handlers,
    get_inbox_trust_wedge_service_instance,
    handle_send_email,
    handle_reply_email,
    handle_archive_message,
    handle_trash_message,
    handle_restore_message,
    handle_snooze_message,
    handle_mark_read,
    handle_mark_unread,
    handle_star_message,
    handle_unstar_message,
    handle_move_to_folder,
    handle_add_label,
    handle_remove_label,
    handle_batch_archive,
    handle_batch_trash,
    handle_batch_modify,
    handle_get_action_logs,
    handle_export_action_logs,
)
from .trust_wedge_handler import InboxTrustWedgeHandler

from .team_inbox import (
    get_team_inbox_handlers,
    handle_get_team_members,
    handle_add_team_member,
    handle_remove_team_member,
    handle_start_viewing,
    handle_stop_viewing,
    handle_start_typing,
    handle_stop_typing,
    handle_get_notes,
    handle_add_note,
    handle_get_mentions,
    handle_acknowledge_mention,
    handle_get_activity_feed,
)

__all__ = [
    # Action items handlers
    "handle_extract_action_items",
    "handle_list_pending_actions",
    "handle_complete_action",
    "handle_update_action_status",
    "handle_get_due_soon",
    "handle_batch_extract",
    "handle_detect_meeting",
    "handle_auto_snooze_meeting",
    "get_action_items_handlers",
    # Email actions handlers
    "handle_send_email",
    "handle_reply_email",
    "handle_archive_message",
    "handle_trash_message",
    "handle_restore_message",
    "handle_snooze_message",
    "handle_mark_read",
    "handle_mark_unread",
    "handle_star_message",
    "handle_unstar_message",
    "handle_move_to_folder",
    "handle_add_label",
    "handle_remove_label",
    "handle_batch_archive",
    "handle_batch_trash",
    "handle_batch_modify",
    "handle_get_action_logs",
    "handle_export_action_logs",
    "get_email_actions_handlers",
    "get_inbox_trust_wedge_service_instance",
    "InboxTrustWedgeHandler",
    # Team inbox handlers
    "handle_get_team_members",
    "handle_add_team_member",
    "handle_remove_team_member",
    "handle_start_viewing",
    "handle_stop_viewing",
    "handle_start_typing",
    "handle_stop_typing",
    "handle_get_notes",
    "handle_add_note",
    "handle_get_mentions",
    "handle_acknowledge_mention",
    "handle_get_activity_feed",
    "get_team_inbox_handlers",
]

"""Matrix channel adapter for carapace.

Connects to a Matrix homeserver via matrix-nio (plain-text, no E2EE for now).
Maps one session per room; supports slash commands including /reset.
"""

from __future__ import annotations

from .approval import PendingApproval as _PendingApproval
from .approval import PendingCredentialApproval as _PendingCredentialApproval
from .approval import PendingDomainApproval as _PendingDomainApproval
from .channel import MatrixChannel
from .formatting import (
    format_approval_request as _format_approval_request,
)
from .formatting import (
    format_command_result_text as _format_command_result_text,
)
from .formatting import (
    format_domain_escalation as _format_domain_escalation,
)
from .formatting import (
    md_to_html as _md_to_html,
)

__all__ = [
    "MatrixChannel",
    "_PendingApproval",
    "_PendingCredentialApproval",
    "_PendingDomainApproval",
    "_format_approval_request",
    "_format_command_result_text",
    "_format_domain_escalation",
    "_md_to_html",
]

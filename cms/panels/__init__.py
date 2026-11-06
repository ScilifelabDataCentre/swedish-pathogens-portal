"""Panels for the CMS."""

from .settings_panel import EmailPasswordPanel
from .workflow_panel import CustomUserObjectsInWorkflowModerationPanel

__all__ = [
    "CustomUserObjectsInWorkflowModerationPanel",
    "EmailPasswordPanel",
]

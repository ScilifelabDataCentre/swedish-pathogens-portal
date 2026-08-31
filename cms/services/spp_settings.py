"""Helper functions for getting spp settings."""

from cms.site_settings.spp_settings import SppSettings


def direct_publishing_disabled() -> bool:
    """Check if direct publishing is disabled in the approval settings."""
    return SppSettings.load().disable_direct_publishing


def self_approval_disabled() -> bool:
    """Check if self approval is disabled in the approval settings."""
    return SppSettings.load().disable_self_approval

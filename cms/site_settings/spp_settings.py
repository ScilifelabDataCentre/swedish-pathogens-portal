"""Page approval related settings and tasks for the CMS."""

from django.db import models
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.contrib.settings.models import BaseGenericSetting, register_setting


@register_setting(icon="desktop")
class SppSettings(BaseGenericSetting):
    """Site settings for the CMS.

    This class defines the site setting model, which can be used to store and manage
    site wide settings. This is mainly meant for UI behaviour, workflow control and
    other similar settings. Benefit of this over configurations in the settings.py
    file is that these can be set and modified by the site admin without requiring
    a code change or redeployment of the application.

    These settings are stored in the database and can be accessed in the code using
    the `SppSettings.load()` method.

    Attributes:
        disable_direct_publishing (bool): If True, direct publishing of pages is disabled.
        disable_self_approval (bool): If True, self approval of pages is disabled.
    """

    disable_direct_publishing = models.BooleanField(
        default=False,
        help_text="Prevent users from publishing pages directly.",
    )
    disable_self_approval = models.BooleanField(
        default=False,
        help_text="Prevent users from approving their own changes.",
    )

    panels = [
        MultiFieldPanel(
            [
                FieldPanel("disable_direct_publishing"),
                FieldPanel("disable_self_approval"),
            ],
            heading="Approval Settings",
        ),
    ]

    class Meta:
        """Meta class for the SppSettings model."""

        verbose_name = "SPP Settings"
        verbose_name_plural = "SPP Settings"

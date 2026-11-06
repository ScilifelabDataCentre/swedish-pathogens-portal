"""Panels for the wagtailadmin account settings."""

from django import forms
from wagtail.admin.views.account import BaseSettingsPanel


class EmptyForm(forms.Form):
    """An empty form for a links-only settings panel."""

    def __init__(self, *args, **kwargs) -> None:
        """Override the init method to remove the instance argument, as this form has no fields."""
        kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)

    def save(self) -> None:
        """Override save method to do nothing, as this form has no fields."""
        pass


class EmailPasswordPanel(BaseSettingsPanel):
    """A custom account settings panel to display links for managing email and password.

    The wagtail's email and password management is disabled, and this panel is used
    to display the django-allauth management links in wagtail account settings page.
    Since this panel does not have any form fields, it uses an empty form as the form
    class is required by wagtail's BaseSettingsPanel. The template used for this panel
    is located at `core/templates` instead of `cms/templates` because we already have
    a `wagtailadmin` directory in `core/templates` and it is more appropriate to place
    the template there, as it is related to wagtail's account settings.
    """

    name = "email_password"
    title = "Email and Password"
    description = "Manage your email and password settings."
    order = 150

    form_class = EmptyForm
    template_name = "wagtailadmin/settings_panels/email_password.html"

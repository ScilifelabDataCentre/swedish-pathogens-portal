"""Views utility for Pathogens Portal.

Commonly used custom view class can be found here.
The classes should be defined in a separate file
within 'utils/views' and then imported here for
easy/tidy import during usage. Names of the classes
imported in this file should also be added to __all__
"""

from ._base_template_view import BaseTemplateView
from ._base_list_view import BaseListView
from ._base_detail_view import BaseDetailView

__all__ = ["BaseTemplateView", "BaseListView", "BaseDetailView"]

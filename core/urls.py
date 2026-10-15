"""URL configuration for Pathogens Portal project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/

Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))

"""

# Third-party imports
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.contrib.sitemaps.views import sitemap as wagtail_sitemap
from wagtail.documents import urls as wagtaildocs_urls

# Local imports
from cms.views.search import search, search_autocomplete
from core.views import ebi_index, healthz

# Own handled URLs (takes precedence over third-party apps)
# These are URLs that are handled by views we develop and maintain, not by third-party apps.
# ----------------------------------------------------------------------------------------
own_view_urls = [
    path("cms/", include("cms.urls")),
    path("ebi-index.json", ebi_index, name="ebi_index"),
    path("healthz/", healthz, name="healthz"),
    path("search/", search, name="search"),
    path("search/autocomplete/", search_autocomplete, name="search_autocomplete"),
]


# Third-party app URLs (Wagtail, Django, etc.)
# These are URLs that are handled by third-party apps, we don't control the views.
# ----------------------------------------------------------------------------------------
third_party_view_urls = [
    path(settings.WAGTAILADMIN_URL, include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    path("sitemap.xml", wagtail_sitemap, name="sitemap"),
    # Any URL that was not matched by an explicit URL above are tried and handled by Wagtail.
    # Wagtail raises 404, if it couldn't find a Page or Route handler for the URL
    path("", include(wagtail_urls)),
]


# Django admin URL (optional)
# No need for this as most of the admin functionality is handled by Wagtail, but it can be
# included if needed for special cases. If included, it takes precedence over Wagtail URLs
# ----------------------------------------------------------------------------------------
if settings.INCLUDE_DJANGO_ADMIN:
    third_party_view_urls = [
        path(settings.DJANGO_ADMIN_URL, admin.site.urls),
    ] + third_party_view_urls


# Combine all URL patterns into a single list, in order of precedence.
urlpatterns = own_view_urls + third_party_view_urls


# Local development URLs (when DEBUG is True)
# Adds support for django-browser-reload and serving media files in development.
# ----------------------------------------------------------------------------------------
if settings.DEBUG:
    debug_urls = [
        path("__reload__/", include("django_browser_reload.urls")),
    ]
    # Serve media files in development
    debug_urls += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    # Though added first, this doesn't affect other URL patterns. Adding it last causes
    # issues because of path("", include(wagtail_urls)) which matches everything and would
    # prevent the debug URLs from being matched.
    urlpatterns = debug_urls + urlpatterns

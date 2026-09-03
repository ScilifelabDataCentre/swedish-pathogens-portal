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
from wagtail.contrib.sitemaps.views import sitemap

# Local imports
from core.views import healthz

urlpatterns = []

# Include Django admin URLs if enabled in settings.
if settings.INCLUDE_DJANGO_ADMIN:
    urlpatterns += [
        path(settings.DJANGO_ADMIN_URL, admin.site.urls),
    ]

# General URLs for health checks and sitemap.
urlpatterns += [
    path("healthz/", healthz, name="healthz"),
    path("sitemap.xml", sitemap, name="sitemap"),
]

# Auto browser reload addition for local development
if settings.DEBUG:
    urlpatterns += [
        path("__reload__/", include("django_browser_reload.urls")),
    ]
    # Serve media files in development
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Wagtail admin and CMS URLs
urlpatterns += [
    path(settings.WAGTAILADMIN_URL, include(wagtailadmin_urls)),
    path("cms/", include("cms.urls")),
    # Any URL that was not matched by an explicit URL above are tried and handled by Wagtail.
    # Wagtail raises 404, if it couldn't find a Page or Route handler for the URL
    path("", include(wagtail_urls)),
]

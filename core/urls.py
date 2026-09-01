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

# Local imports
from core.views import ebi_index, healthz

# not part of public scan - skipping namespace
urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls, name="admin"),
    path("healthz/", healthz, name="healthz"),
    path("ebi-index.json", ebi_index, name="ebi_index"),
]
# Auto browser reload addition for local development
if settings.DEBUG:
    urlpatterns += [
        path("__reload__/", include("django_browser_reload.urls")),
    ]
    # Serve media files in development
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += [
    path(settings.WAGTAILADMIN_URL, include(wagtailadmin_urls)),
    path("cms/", include("cms.urls")),
    # Any URL that was not matched by an explicit URL above are tried and handled by Wagtail.
    # Wagtail raises 404, if it couldn't find a Page or Route handler for the URL
    path("", include(wagtail_urls)),
]

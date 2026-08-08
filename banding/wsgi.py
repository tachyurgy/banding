import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "")
from banding import app  # noqa: F401,E402  (configures settings on import)

application = get_wsgi_application()

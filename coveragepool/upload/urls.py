from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^coveragefile/$', views.coveragefile, name='coveragefile')
]

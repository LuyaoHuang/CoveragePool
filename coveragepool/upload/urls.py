from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^coveragefile/$', views.coveragefile, name='coveragefile'),
    url(r'^listfile/$', views.listfile, name='listfile'),
    url(r'^syncdata/$', views.sync_data, name='sync_data'),
]

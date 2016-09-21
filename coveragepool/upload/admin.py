from django.contrib import admin
from .models import CoverageFile

# Register your models here.
class CoverageFileAdmin(admin.ModelAdmin):
    list_display = ('name', 'user_name', 'version', 'date', 'coveragefile')
    list_filter = ('user_name', 'version')
    date_hierarchy = 'date'

admin.site.register(CoverageFile, CoverageFileAdmin)

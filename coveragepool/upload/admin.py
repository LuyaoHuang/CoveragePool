from django.contrib import admin
from .models import CoverageFile, CoverageReport, Project

# Register your models here.
class CoverageFileAdmin(admin.ModelAdmin):
    list_display = ('name', 'user_name', 'version',
                    'date', 'coveragefile', 'project')
    list_filter = ('user_name', 'version', 'project')
    search_fields = ('name',)
    date_hierarchy = 'date'

admin.site.register(CoverageFile, CoverageFileAdmin)

class CoverageReportAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'version', 'date',
                    'tracefile', 'rules', 'url', 'path')
    list_filter = ('version', 'project')
    search_fields = ('name',)
    date_hierarchy = 'date'

admin.site.register(CoverageReport, CoverageReportAdmin)

class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'base_dir', 'base_url', 'pkg_name',
                    'tag_fmt', 'git_repo', 'gs_key', 'gs_json_file')

admin.site.register(Project, ProjectAdmin)

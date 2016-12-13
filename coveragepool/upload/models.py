from __future__ import unicode_literals

from django.db import models
from django.dispatch import receiver
from django.db.models.signals import post_delete
from django.core.files import File
import random
import shutil
import datetime

def content_file_name(instance, filename):
    hash = random.getrandbits(128)
    file_name = '%032x-%s' % (hash, filename)
    return 'coveragefile/%s' % file_name

# Create your models here.
class Project(models.Model):
    name = models.CharField(max_length=100, unique=True)
    base_dir = models.CharField(max_length=100, null=True)
    base_url = models.CharField(max_length=100, null=True)
    tag_fmt = models.CharField(max_length=100, null=True)
    git_repo = models.CharField(max_length=255, null=True)
    # Google sheet db
    gs_key = models.CharField(max_length=255, null=True)
    gs_json_file = models.CharField(max_length=100, null=True)

    def __str__(self):
        return self.name

class CoverageFile(models.Model):
    project = models.ForeignKey(Project, null=True)
    name = models.CharField(max_length=100)
    user_name = models.CharField(max_length=100)
    version = models.CharField(max_length=100)
    date = models.DateTimeField(default=datetime.datetime.now)
    coveragefile = models.FileField(upload_to=content_file_name)

class CoverageReport(models.Model):
    project = models.ForeignKey(Project, null=True)
    name = models.CharField(max_length=100)
    version = models.CharField(max_length=100)
    date = models.DateTimeField(default=datetime.datetime.now)
    path = models.CharField(max_length=100, blank=True, null=True)
    url = models.CharField(max_length=100, blank=True, null=True)
    tracefile = models.FileField(null=True, upload_to=content_file_name)
    rules = models.CharField(max_length=100, blank=True, null=True)
    coverage_files = models.ManyToManyField(CoverageFile)

    def save_tracefile(self, tracefile):
        name = 'merged_report_%d' % self.id
        with open(tracefile) as fp:
            myfile = File(fp)
            self.tracefile.save(name, myfile)

@receiver(post_delete, sender=CoverageFile)
def CoverageFile_post_delete_handler(sender, instance, **kwargs):
    instance.coveragefile.delete(save=False)

@receiver(post_delete, sender=CoverageReport)
def CoverageReport_post_delete_handler(sender, instance, **kwargs):
    if instance.path:
        shutil.rmtree(instance.path, True)
    if instance.tracefile:
        instance.tracefile.delete(save=False)

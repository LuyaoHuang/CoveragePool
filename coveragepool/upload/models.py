from __future__ import unicode_literals

from django.db import models
from django.dispatch import receiver
from django.db.models.signals import post_delete
import random
import shutil

def content_file_name(instance, filename):
    hash = random.getrandbits(128)
    file_name = '%032x-%s' % (hash, filename)
    return 'coveragefile/%s' % file_name

# Create your models here.
class CoverageFile(models.Model):
    name = models.CharField(max_length=100)
    user_name = models.CharField(max_length=100)
    version = models.CharField(max_length=100)
    date = models.DateTimeField()
    coveragefile = models.FileField(upload_to=content_file_name)

class CoverageReport(models.Model):
    name = models.CharField(max_length=100)
    version = models.CharField(max_length=100)
    date = models.DateTimeField()
    path = models.CharField(max_length=100, blank=True, null=True)
    url = models.CharField(max_length=100, blank=True, null=True)
    coverage_files = models.ManyToManyField(CoverageFile)

@receiver(post_delete, sender=CoverageFile)
def CoverageFile_post_delete_handler(sender, **kwargs):
    instance.coveragefile.delete(save=False)

@receiver(post_delete, sender=CoverageReport)
def CoverageReport_post_delete_handler(sender, **kwargs):
    if instance.path:
        shutil.rmtree(instance.path)

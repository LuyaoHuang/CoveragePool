from __future__ import unicode_literals

from django.db import models
import random

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

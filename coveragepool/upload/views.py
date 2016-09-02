from django.shortcuts import render
from django.http import HttpResponse
from .models import CoverageFile
from dateutil import parser
import time
from django.views.decorators.csrf import csrf_exempt
from .forms import UploadFileForm

# Create your views here.

@csrf_exempt
def coveragefile(request):
    if 'name' not in request.POST.keys():
        return HttpResponse("Need pass name", content_type="text/plain; charset=utf-8")
    if 'version' not in request.POST.keys():
        return HttpResponse("Need pass version", content_type="text/plain; charset=utf-8")
    if 'coveragefile' not in request.FILES.keys():
        return HttpResponse("Need pass coveragefile", content_type="text/plain; charset=utf-8")

    name = request.POST.get('name')
    version = request.POST.get('version')
    coveragefile = request.FILES['coveragefile']

    date = parser.parse(time.ctime()).replace(tzinfo=None)
    cf = CoverageFile.objects.create(name=name,
                                     coveragefile=request.FILES['coveragefile'],
                                     date=date, version=version)
    cf.save()
    return HttpResponse("OK", content_type="text/plain; charset=utf-8")

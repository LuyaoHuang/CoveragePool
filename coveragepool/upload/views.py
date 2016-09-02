from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from .models import CoverageFile
from dateutil import parser
import time
from django.views.decorators.csrf import csrf_exempt
from django.forms.models import model_to_dict

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


def listfile(request):
    ret = []

    print request.POST
    if 'name' in request.POST.keys():
        objs = CoverageFile.objects.filter(name=request.POST['name'])
    else:
        objs = CoverageFile.objects.all()

    for obj in objs:
        tmp_json = model_to_dict(obj)
        tmp_json['date'] = tmp_json['date'].strftime("%Y-%m-%d %H:%M:%S")
        tmp_json['coveragefile'] = tmp_json['coveragefile'].name
        ret.append(tmp_json)

    return JsonResponse({'data': ret})

from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from .models import CoverageFile
from dateutil import parser
import time
from django.views.decorators.csrf import csrf_exempt
from django.forms.models import model_to_dict

# Create your views here.

def request_check(request, check_dict):
    for i in check_dict.keys():
        if i == 'post':
            check_list = request.POST.keys()
        elif i == 'files':
            check_list = request.FILES.keys()
        else:
            raise Exception("Unkown type %s" % i)

        for n in check_dict[i]:
            if n not in check_list:
                return 1, "Need pass %s" % n

    return 0, "Pass"


@csrf_exempt
def coveragefile(request):
    ret, msg = request_check(request, {'post': ['name', 'version', 'user_name'],
                                       'files': ['coveragefile']})
    if ret == 1:
        return HttpResponse(msg, content_type="text/plain; charset=utf-8")

    name = request.POST.get('name')
    user_name = request.POST.get('user_name')
    version = request.POST.get('version')
    coveragefile = request.FILES['coveragefile']

    date = parser.parse(time.ctime()).replace(tzinfo=None)
    cf = CoverageFile.objects.create(name=name,
                                     user_name=user_name,
                                     coveragefile=request.FILES['coveragefile'],
                                     date=date, version=version)
    cf.save()
    return HttpResponse("OK", content_type="text/plain; charset=utf-8")


def listfile(request):
    ret = []

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

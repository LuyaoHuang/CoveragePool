from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.forms.models import model_to_dict
from django.conf import settings

import time
import os
from dateutil import parser
from .models import CoverageFile, Project
from gen_report.utils import parse_package_name
from gen_report.tasks import prepare_gsmgr

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


# TODO: move to utils module
def get_size(start_path = '.'):
    """
    Check directroy size
    """
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(start_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total_size += os.path.getsize(fp)
        for dir in dirnames:
            dir_path = os.path.join(dirpath, dir)
            total_size += get_size(dir_path)
        return total_size

def check_media_limit():
    media_dir = getattr(settings, "MEDIA_ROOT", None)
    media_limit = getattr(settings, "COVERAGE_MEDIA_LIMIT_SIZE", None)
    if not media_limit:
        return False
    return get_size(media_dir) > int(media_limit)


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
    # TODO: Not all platform use rpm package system
    pkg_name, _, _, _ = parse_package_name(version)
    projects = Project.objects.filter(pkg_name=pkg_name)
    if len(projects) == 1:
        project = projects[0]
    elif len(projects) > 1:
        raise Exception('Find more than one project point to one pkg %s' % pkg_name)
    else:
        project = None

    date = parser.parse(time.ctime()).replace(tzinfo=None)
    cf = CoverageFile.objects.create(name=name,
                                     project=project,
                                     user_name=user_name,
                                     coveragefile=request.FILES['coveragefile'],
                                     date=date, version=version)
    cf.save()
    if check_media_limit():
        cf.delete()
        return HttpResponse("ERROR: Fail to upload file: Media directroy size limited",
                            content_type="text/plain; charset=utf-8")

    gs = prepare_gsmgr(project)
    if gs:
        gs.add_new_row_by_dict({"Id": cf.id,
                                "Name": name,
                                "User Name": user_name,
                                "Version": version,
                                "Date": cf.date.strftime("%Y-%m-%d %H:%M:%S")})

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


def sync_data(request):
    projects = Project.objects.all()
    projects.append(None)

    for project in projects:
        objs = CoverageFile.objects.filter(project=project)
        gs = prepare_gsmgr(project)
        if not gs:
            # TODO:logging
            continue
        for i, obj in enumerate(objs):
            gs.add_new_row_by_dict({"Id": obj.id,
                                    "Name": obj.name,
                                    "User Name": obj.user_name,
                                    "Version": obj.version,
                                    "Date": obj.date.strftime("%Y-%m-%d %H:%M:%S")}, row=i+2)

    return HttpResponse("Done!\n", content_type="text/plain; charset=utf-8")

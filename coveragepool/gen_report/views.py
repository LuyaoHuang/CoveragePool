from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from . import tasks

# Create your views here.
def test(request):
    res = tasks.first_test.delay()
    return HttpResponse("OK", content_type="text/plain; charset=utf-8")

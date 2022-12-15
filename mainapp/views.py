from django.http import HttpResponse
from django.shortcuts import render

from integrations.collector import collect


def index(request):
    return HttpResponse(collect("plausible"))
    return HttpResponse("Hello, world. You're at the index.")

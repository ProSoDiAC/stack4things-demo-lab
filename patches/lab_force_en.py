# -*- coding: utf-8 -*-
"""Force English UI for lab Horizon (Python 2.7 / Django 1.x)."""


class ForceEnglishMiddleware(object):
    def process_request(self, request):
        from django.utils import translation
        translation.activate('en')
        request.LANGUAGE_CODE = 'en'
        return None

    def process_response(self, request, response):
        from django.utils import translation
        translation.deactivate()
        return response

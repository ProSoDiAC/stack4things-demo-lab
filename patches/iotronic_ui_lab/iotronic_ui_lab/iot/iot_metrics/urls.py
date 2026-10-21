# -*- coding: utf-8 -*-

from django.conf.urls import url

from iotronic_ui_lab.iot.iot_metrics import views


urlpatterns = [
    url(r"^$", views.IndexView.as_view(), name="index"),
]

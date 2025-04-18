from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . views import GetExcel

urlpatterns = [
    path('Getexcel', GetExcel.as_view(), name='Getexcel')
]
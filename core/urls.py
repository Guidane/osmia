from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('images/<int:pk>/', views.image_file, name='image'),
    path('images/<int:pk>/update/', views.image_update, name='image_update'),
    path('images/add/<str:model>/<int:pk>/', views.image_upload, name='image_upload'),
]

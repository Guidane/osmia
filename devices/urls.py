from django.urls import path

from . import views

urlpatterns = [
    path('', views.DeviceListView.as_view(), name='list'),
    path('new/', views.DeviceCreateView.as_view(), name='create'),
    path('<int:pk>/', views.DeviceDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.DeviceUpdateView.as_view(), name='edit'),
    path('<int:pk>/versions/<int:version>/activate/', views.activate_version, name='activate_version'),
    path('<int:device_pk>/connectors/new/', views.connector_form, name='connector_create'),
    path('<int:device_pk>/connectors/<int:pk>/', views.connector_form, name='connector_edit'),
    path('<int:device_pk>/connectors/<int:pk>/delete/', views.connector_delete, name='connector_delete'),
    path('from-assembly/<int:assembly_pk>/', views.device_from_assembly, name='from_assembly'),
]

from django.urls import path

from . import views

urlpatterns = [
    path('', views.ProjectListView.as_view(), name='list'),
    path('designer/', views.designer, name='designer'),
    path('api/devices', views.api_devices, name='api_devices'),
    path('api/devices/<int:pk>', views.api_device, name='api_device'),
    path('api/devices/<int:pk>/versions', views.api_device_versions),
    path('api/devices/<int:pk>/versions/<int:version>/activate', views.api_device_activate),
    path('api/projects', views.api_projects, name='api_projects'),
    path('api/projects/<int:pk>', views.api_project, name='api_project'),
    path('api/projects/<int:pk>/versions', views.api_project_versions),
    path('api/projects/<int:pk>/versions/<int:version>/activate', views.api_project_activate),
    path('api/signal-rules', views.api_signal_rules, name='api_signal_rules'),
    path('api/users', views.api_users, name='api_users'),
]

from django.urls import path

from . import views

urlpatterns = [
    path('', views.PartListView.as_view(), name='part_list'),
    path('parts/new/', views.PartCreateView.as_view(), name='part_create'),
    path('parts/<int:pk>/', views.PartDetailView.as_view(), name='part_detail'),
    path('parts/<int:pk>/edit/', views.PartUpdateView.as_view(), name='part_edit'),
    path('parts/lookup/', views.part_lookup, name='part_lookup'),
    path('moves/', views.MoveListView.as_view(), name='move_list'),
    path('moves/new/', views.MoveCreateView.as_view(), name='move_create'),
    path('categories/', views.CategoryListView.as_view(), name='category_list'),
    path('categories/new/', views.category_form, name='category_create'),
    path('categories/<int:pk>/', views.category_form, name='category_edit'),
    path('categories/<int:pk>/attributes/add/', views.category_add_attributes, name='category_add_attributes'),
    path('locations/', views.LocationListView.as_view(), name='location_list'),
    path('locations/new/', views.LocationCreateView.as_view(), name='location_create'),
    path('locations/<int:pk>/', views.LocationUpdateView.as_view(), name='location_edit'),
]

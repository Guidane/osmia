from django.urls import path

from . import views

urlpatterns = [
    path('', views.BudgetListView.as_view(), name='list'),
    path('new/', views.BudgetCreateView.as_view(), name='create'),
    path('<int:pk>/', views.BudgetDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.BudgetUpdateView.as_view(), name='edit'),
    path('link-task/<int:task_pk>/', views.link_task, name='link_task'),
]

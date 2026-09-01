from django.urls import path
from . import views

app_name = 'repositories'

urlpatterns = [
    path('', views.list_repositories, name='list'),
    path('submit/', views.submit_repository, name='submit'),
    path('<int:repository_id>/', views.repository_detail, name='detail'),
    path('<int:snapshot_id>/prepare/', views.prepare_analysis, name='prepare'),
]

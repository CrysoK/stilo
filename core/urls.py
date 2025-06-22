from django.urls import path
from django.contrib.auth.views import LogoutView
from django.views.generic import TemplateView
from .views import (
    HomeView,
    HairdresserDetailView,
    SignUpView,
    CustomLoginView,
    ServiceListView,
    ServiceCreateView,
    ServiceUpdateView,
    ServiceDeleteView,
    AppointmentListView,
    hairdresser_map_data,
    OwnerDashboardView,
    earnings_chart_data,
)

urlpatterns = [
    # URLs de Autenticación y Home
    path("", HomeView.as_view(), name="home"),
    path("signup/", SignUpView.as_view(), name="signup"),
    path("login/", CustomLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(next_page="home"), name="logout"),
    # URLs del CRUD de Servicios
    path("dashboard/", OwnerDashboardView.as_view(), name="owner_dashboard"),
    path("my-services/", ServiceListView.as_view(), name="service_list"),
    path("my-services/new/", ServiceCreateView.as_view(), name="service_create"),
    path(
        "my-services/<int:pk>/edit/", ServiceUpdateView.as_view(), name="service_update"
    ),
    path(
        "my-services/<int:pk>/delete/",
        ServiceDeleteView.as_view(),
        name="service_delete",
    ),
    path(
        "hairdresser/<int:pk>/",
        HairdresserDetailView.as_view(),
        name="hairdresser_detail",
    ),
    path("my-appointments/", AppointmentListView.as_view(), name="my_appointments"),
    # URLs de la API
    path("api/map-data/", hairdresser_map_data, name="map_data"),
    path("api/earnings-chart/", earnings_chart_data, name="earnings_chart_data"),
]

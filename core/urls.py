from django.urls import path
from django.contrib.auth.views import LogoutView
from django.views.generic import RedirectView
from .views import (
    HomeView,
    HairdresserDetailView,
    SignUpView,
    CustomLoginView,
    ServiceCreateView,
    ServiceUpdateView,
    ServiceDeleteView,
    AppointmentListView,
    ReviewCreateView,
    ReviewUpdateView,
    ReviewDeleteView,
    get_review_detail,
    appointment_events_data,
    hairdresser_map_data,
    OwnerStatsView,
    earnings_chart_data,
    revenue_by_service_chart_data,
    busiest_days_chart_data,
    WorkstationView,
    update_appointment_status,
    MyHairdresserInfoView,
    MyHairdresserHoursView,
    MyHairdresserServicesView,
    MyHairdresserImagesView,
    SetCoverImageView,
    HairdresserImageDeleteView,
    UserProfileView,
    CustomPasswordChangeView,
    get_service_detail,
)

urlpatterns = [
    # URLs de Autenticación y Home
    path("", HomeView.as_view(), name="home"),
    path("signup/", SignUpView.as_view(), name="signup"),
    path("login/", CustomLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(next_page="home"), name="logout"),
    # URLs del CRUD de Servicios
    path("stats/", OwnerStatsView.as_view(), name="owner_stats"),
    path("workstation/", WorkstationView.as_view(), name="workstation"),
    path(
        "workstation/appointment/<int:pk>/update-status/",
        update_appointment_status,
        name="update_appointment_status",
    ),
    path(
        "my-hairdresser/",
        RedirectView.as_view(pattern_name="my_hairdresser_info", permanent=False),
        name="my_hairdresser",
    ),
    path(
        "my-hairdresser/info/",
        MyHairdresserInfoView.as_view(),
        name="my_hairdresser_info",
    ),
    path(
        "my-hairdresser/hours/",
        MyHairdresserHoursView.as_view(),
        name="my_hairdresser_hours",
    ),
    path(
        "my-hairdresser/services/",
        MyHairdresserServicesView.as_view(),
        name="my_hairdresser_services",
    ),
    path(
        "my-hairdresser/images/",
        MyHairdresserImagesView.as_view(),
        name="my_hairdresser_images",
    ),
    path(
        "my-hairdresser/images/<int:pk>/delete/",
        HairdresserImageDeleteView.as_view(),
        name="hairdresser_image_delete",
    ),
    path(
        "my-hairdresser/images/<int:pk>/set-cover/",
        SetCoverImageView.as_view(),
        name="set_cover_image",
    ),
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
    path(
        "appointment/<int:pk>/review/create/",
        ReviewCreateView.as_view(),
        name="review_create",
    ),
    path("review/<int:pk>/update/", ReviewUpdateView.as_view(), name="review_update"),
    path("review/<int:pk>/delete/", ReviewDeleteView.as_view(), name="review_delete"),
    path("api/review/<int:pk>/", get_review_detail, name="review_detail_api"),
    path("profile/", UserProfileView.as_view(), name="user_profile"),
    path(
        "profile/password/", CustomPasswordChangeView.as_view(), name="password_change"
    ),
    # URLs de la API
    path("api/map-data/", hairdresser_map_data, name="map_data"),
    path("api/earnings-chart/", earnings_chart_data, name="earnings_chart_data"),
    path(
        "api/revenue-by-service-chart/",
        revenue_by_service_chart_data,
        name="revenue_by_service_chart",
    ),
    path(
        "api/busiest-days-chart/",
        busiest_days_chart_data,
        name="busiest_days_chart",
    ),
    path(
        "api/hairdresser/<int:hairdresser_id>/events/",
        appointment_events_data,
        name="appointment_events",
    ),
    path("api/services/<int:pk>/", get_service_detail, name="service_detail"),
]

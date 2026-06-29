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
    OwnerAppointmentListView,
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
    geocode_address_api,
    send_reminders_view,
    push_subscribe,
    push_unsubscribe,
    service_worker,
    mercadopago_auth_redirect,
    mercadopago_callback,
    mercadopago_unlink,
    cancel_expired_appointments_view,
    email_preview_list,
    email_preview_render,
    retry_refunds_cron_view,
    refresh_mercadopago_tokens_cron_view,
)
from .webhooks import mercadopago_webhook

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
        "my-hairdresser/appointments/",
        OwnerAppointmentListView.as_view(),
        name="owner_appointments",
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
    path("api/geocode/", geocode_address_api, name="geocode_address_api"),
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
    path("tasks/send-reminders/", send_reminders_view, name="send_reminders"),
    path(
        "tasks/cancel-expired/",
        cancel_expired_appointments_view,
        name="cancel_expired_appointments_endpoint",
    ),
    path(
        "tasks/retry-refunds/",
        retry_refunds_cron_view,
        name="retry_refunds_cron_endpoint",
    ),
    path(
        "tasks/refresh-tokens/",
        refresh_mercadopago_tokens_cron_view,
        name="refresh_mercadopago_tokens_cron_endpoint",
    ),
    path("api/push-subscribe/", push_subscribe, name="push_subscribe"),
    path("api/push-unsubscribe/", push_unsubscribe, name="push_unsubscribe"),
    path("service-worker.js", service_worker, name="service_worker"),
    path(
        "webhooks/mercadopago/<int:hairdresser_id>/",
        mercadopago_webhook,
        name="mercadopago_webhook",
    ),
    path(
        "mercadopago/connect/",
        mercadopago_auth_redirect,
        name="mercadopago_auth_redirect",
    ),
    path("mercadopago/callback/", mercadopago_callback, name="mercadopago_callback"),
    path("mercadopago/unlink/", mercadopago_unlink, name="mercadopago_unlink"),
    # URLs de previsualización de correos
    path("debug/emails/", email_preview_list, name="email_preview_list"),
    path(
        "debug/emails/<str:template_name>/",
        email_preview_render,
        name="email_preview_render",
    ),
]

# Protocol notes

Necto's website exposes an undocumented Inertia-based flow. A successful login
used a JSON `POST /login` with `email`, `password` and `remember`, an XSRF
request header, and a redirect to `/devices`. The device list is available as
an authenticated `GET /devices` response with device fields including
`device_id`, `name`, `latest_report`, `latest_report_at`, `is_offline` and
`is_powered_off`; the latest report includes `temp_val`, `humi_val` and `event`.
The response is paginated. These details are subject to change without notice.

The device page also has a `/devices/<id>/refresh` control that may request a
new measurement. This integration does not invoke that control when polling.

The initial CSRF-cookie acquisition, unsuccessful login responses, session
expiry and Celsius temperature behavior have not been independently verified.
The implementation and synthetic tests are experimental and do not establish
working behavior against the Necto service or Home Assistant.

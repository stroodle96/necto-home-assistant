# Necto Home Assistant integration — experimental

This is an experimental development build. Initial setup and displayed values
have been checked with one live Necto account and Home Assistant instance.
Ongoing polling, session renewal and recovery still need live verification.
Do not rely on it for monitoring or alerts until those tests succeed. It uses the undocumented Necto website,
which may change without notice. Google sign-in is not supported.

The integration is designed to expose temperature, humidity, last report,
last event, offline state, and powered-off state. It polls stored cloud data
every ten minutes and does not call Necto's device-refresh command. Only
Fahrenheit has been observed; temperature is withheld for other units until
their meaning is verified. Readings can be old, so check the last-report time.
Temperature and humidity remain available for one hour after the device's last
report, including during a temporary polling failure or an offline/power-off
status. They become unavailable at one hour; a missing, invalid or future
timestamp does not count as fresh. Last-report and status entities remain
separate diagnostics.

## Installation and experimental testing

For HACS, open **HACS → Custom repositories**, add
`https://github.com/stroodle96/necto-home-assistant` as an **Integration**,
download Necto, and restart Home Assistant. The repository has not yet been
validated by HACS.

For manual installation, copy `custom_components/necto` into Home Assistant's
`config/custom_components/necto` directory and restart Home Assistant.
In **Settings → Devices & services → Add integration**, select
Necto and enter the Necto email and password directly into Home Assistant's
form. Do not send them, cookies, or tokens in chat. Verify each displayed value
and timestamp against the Necto app, then check that updates continue across
session expiry. Remove the integration if it does not behave correctly.

Home Assistant stores config-entry credentials in its local configuration;
anyone with access to that storage or an unprotected backup may be able to read
them. The password can be changed through the integration's reconfiguration
flow, and Home Assistant can request reauthentication if Necto rejects it.
Installation, configuration, and ongoing account access require the user's
approval. No live test or installation has occurred.

See [research notes](NECTO_RESEARCH.md) for confirmed observations and
remaining unknowns. The local tests use synthetic credentials and responses.

The setup approach follows Home Assistant's guidance for [testing a
connection](https://contributors.home-assistant.io/core/quality-scale/test-before-configure/),
[reauthentication](https://contributors.home-assistant.io/core/quality-scale/reauthentication-flow/),
and [reconfiguration](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/reconfiguration-flow/).

## Development tests

Use Python 3.13 to install the Home Assistant test dependencies and run both
suites from the repository root:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m pytest
```

Run the suites in separate processes: the lightweight tests install Home
Assistant stubs, while pytest runs `tests_homeassistant` against the real
Home Assistant runtime. All service responses are synthetic; these tests do
not validate live Necto session renewal.

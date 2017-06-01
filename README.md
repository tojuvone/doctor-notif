# doctor-notif
OPNFV Doctor with inspector notification

This is based on a clone of https://gerrit.opnfv.org/gerrit/doctor

Code under "tests" directory changed to have:
- inspector.py to send notification to rabbit queue
- run.sh changed accordingly and to have alarm of this notification

TBD have installer support to change needed configuration on controllers:
/etc/ceilometer/event_definitions.yaml
TBD inspector.py should not have hardcoded rabbit url, but to use .conf
or some other means

Whole purpose is not to use Nova reset server state to have notification
to have alarm to user, but do this straight from inspector. This change
has proven to get alarm to user from compute host failure 60% faster.
Measuring average alarm to come in ~100ms with this code instead of
~250ms. This was measured in Nokia AirFrame HW running Danube.

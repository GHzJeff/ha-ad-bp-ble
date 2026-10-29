"""A&D Blood Pressure BLE (based on bkbilly/medisanabp_ble)."""

from __future__ import annotations

import logging
from datetime import timedelta

from bluetooth_data_tools import monotonic_time_coarse

from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_last_service_info,
)
from homeassistant.components.bluetooth.active_update_processor import (
    ActiveBluetoothProcessorCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .medisana_bp import MedisanaBPBluetoothDeviceData, SensorUpdate
from .const import DOMAIN

PLATFORMS: list[Platform] = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)

# The A&D only advertises for a short while after a reading, and its advertisement
# never changes, so HA's change-driven polling never fires. Watch the last-seen
# time instead and poll once per advertising burst.
CHECK_INTERVAL = timedelta(seconds=5)
FRESH_SECONDS = 10  # advert seen this recently means the monitor is awake
BURST_GAP_SECONDS = 60  # silence longer than this starts a new burst
RETRY_SECONDS = 20  # retry a failed poll within the same burst


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MedisanaBP BLE device from a config entry."""
    address = entry.unique_id
    assert address is not None
    data = MedisanaBPBluetoothDeviceData()

    def _proxy_hears(addr: str) -> bool:
        """True if an ESPHome proxy (not a local adapter) currently hears addr.

        Only the proxy can pair with the monitor. If HA connects before the proxy
        has reported the advertisement, it tries hci0 alone, burns ~20 s failing,
        and the monitor stops advertising before the proxy gets a turn.
        """
        try:
            from homeassistant.components.bluetooth import (
                async_scanner_devices_by_address,
            )

            return any(
                "path" not in (getattr(d.ble_device, "details", None) or {})
                for d in async_scanner_devices_by_address(hass, addr, True)
            )
        except Exception:  # private-ish API; don't block polling if it changes
            return True

    def _needs_poll(
        service_info: BluetoothServiceInfoBleak, last_poll: float | None
    ) -> bool:
        # Only poll if hass is running, we need to poll,
        # and we actually have a way to connect to the device
        return (
            hass.state is CoreState.running
            and data.poll_needed(service_info, last_poll)
            and _proxy_hears(service_info.device.address)
            and bool(
                service_info.connectable
                or async_ble_device_from_address(
                    hass, service_info.device.address, connectable=True
                )
            )
        )

    def _prefer_proxy_path(addr: str) -> None:
        """Steer HA's connection-path choice to the ESP32 proxy.

        The A&D bond lives on the ESPHome proxy; HA's local BlueZ adapter (hci0)
        can never pair with these monitors (AuthenticationFailed -> monitor shows
        Err 10). habluetooth scores paths by RSSI minus a failure penalty, so after
        a few failures the proxy loses even with a much stronger signal. Clear the
        proxy's failure count and give local adapters a heavy one (private API).
        """
        try:
            from homeassistant.components.bluetooth import (
                async_scanner_devices_by_address,
            )

            devs = async_scanner_devices_by_address(hass, addr, True)

            def _is_local(d) -> bool:
                return "path" in (getattr(d.ble_device, "details", None) or {})

            if not any(not _is_local(d) for d in devs):
                return  # no proxy can hear it; leave HA's choice alone
            for d in devs:
                fails = getattr(d.scanner, "_connect_failures", None)
                if fails is None:
                    continue
                if _is_local(d):
                    fails[addr] = 50
                else:
                    fails.pop(addr, None)
        except Exception as err:  # never block a poll on this
            _LOGGER.debug("Could not steer path for %s: %r", addr, err)

    async def _async_poll(service_info: BluetoothServiceInfoBleak) -> SensorUpdate:
        # BluetoothServiceInfoBleak is defined in HA, otherwise would just pass it
        # directly to the parser code
        # Make sure the device we have is one that we can connect with
        # in case its coming from a passive scanner
        if service_info.connectable:
            connectable_device = service_info.device
        elif device := async_ble_device_from_address(
            hass, service_info.device.address, True
        ):
            connectable_device = device
        else:
            # We have no bluetooth controller that is in range of
            # the device to poll it
            raise RuntimeError(
                f"No connectable device found for {service_info.device.address}"
            )
        if not _proxy_hears(service_info.device.address):
            raise RuntimeError(
                f"{service_info.device.address}: no ESPHome proxy hears it yet"
            )
        _prefer_proxy_path(service_info.device.address)
        update = await data.async_poll(
            connectable_device,
            ble_device_callback=lambda: async_ble_device_from_address(
                hass, service_info.device.address, True
            )
            or connectable_device,
        )
        # One event per stored record so nothing taken offline is lost
        for record in data.session_records:
            when = record["date"] or dt_util.now()
            hass.bus.async_fire(
                f"{DOMAIN}_reading",
                {
                    "address": address,
                    "time": when.replace(microsecond=0).isoformat(),
                    "systolic": record["systolic"],
                    "diastolic": record["diastolic"],
                    "pulse": record["pulse"],
                },
            )
        return update

    coordinator = hass.data.setdefault(DOMAIN, {})[
        entry.entry_id
    ] = ActiveBluetoothProcessorCoordinator(
        hass,
        _LOGGER,
        address=address,
        mode=BluetoothScanningMode.PASSIVE,
        update_method=data.update,
        needs_poll_method=_needs_poll,
        poll_method=_async_poll,
        # We will take advertisements from non-connectable devices
        # since we will trade the BLEDevice for a connectable one
        # if we need to poll it
        connectable=False,
    )
    burst = {"prev_seen": None, "start": None, "polled": None, "attempt": 0.0}

    @callback
    def _async_check_advertising(_now) -> None:
        info = async_last_service_info(hass, address, connectable=True)
        if info is None or coordinator._last_service_info is None:
            return
        seen = info.time
        if burst["prev_seen"] is None or seen - burst["prev_seen"] > BURST_GAP_SECONDS:
            burst["start"] = seen
        burst["prev_seen"] = seen
        now = monotonic_time_coarse()
        if now - seen > FRESH_SECONDS:
            return
        if not _proxy_hears(address):
            return  # wait (up to one CHECK_INTERVAL) for the proxy to report it
        if burst["polled"] == burst["start"] and data._last_poll_successful:
            return
        if now - burst["attempt"] < RETRY_SECONDS:
            return
        burst["attempt"] = now
        burst["polled"] = burst["start"]
        _LOGGER.debug("%s is advertising; polling for new readings", address)
        coordinator._debounced_poll.async_schedule_call()

    entry.async_on_unload(
        async_track_time_interval(hass, _async_check_advertising, CHECK_INTERVAL)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(
        # only start after all platforms have had a chance to subscribe
        coordinator.async_start()
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
#!/usr/bin/env python3
import asyncio
import json
import pathlib
import subprocess

from dbus_next.aio import MessageBus
from dbus_next.constants import BusType

# --- Configuration ---
TARGET_NAME = "Totem"  # substring to identify your keyboard
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
STATE_FILE = pathlib.Path("/tmp/totem_battery.json")
THRESHOLD = 20  # percent


# --- Helper functions ---
def notify(message):
    subprocess.run(["notify-send", "Totem Battery Alert", message])


def load_previous_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_current_state(state):
    STATE_FILE.write_text(json.dumps(state))


# --- D-Bus battery fetching ---
async def find_totem_device(bus):
    root_introspection = await bus.introspect("org.bluez", "/")
    root_obj = bus.get_proxy_object("org.bluez", "/", root_introspection)
    manager = root_obj.get_interface("org.freedesktop.DBus.ObjectManager")
    objects = await manager.call_get_managed_objects()

    for path, interfaces in objects.items():
        dev = interfaces.get("org.bluez.Device1")
        if dev:
            name_variant = dev.get("Name") or dev.get("Alias")
            if name_variant:
                name = name_variant.value
                if TARGET_NAME.lower() in name.lower():
                    return path
    return None


async def read_battery_service(bus, svc_path):
    svc_introspection = await bus.introspect("org.bluez", svc_path)
    svc_proxy = bus.get_proxy_object("org.bluez", svc_path, svc_introspection)

    for char_path in svc_proxy.child_paths:
        char_introspection = await bus.introspect("org.bluez", char_path)
        char_proxy = bus.get_proxy_object("org.bluez", char_path, char_introspection)
        char_iface = char_proxy.get_interface("org.bluez.GattCharacteristic1")
        char_props = char_proxy.get_interface("org.freedesktop.DBus.Properties")

        char_uuid = (
            await char_props.call_get("org.bluez.GattCharacteristic1", "UUID")
        ).value.lower()
        if char_uuid != BATTERY_LEVEL_UUID:
            continue

        value = await char_iface.call_read_value({})
        battery_level = int.from_bytes(value, byteorder="little")
        return battery_level
    return None


async def main():
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    device_path = await find_totem_device(bus)
    if not device_path:
        print("Totem keyboard not found!")
        return

    introspection = await bus.introspect("org.bluez", device_path)
    device = bus.get_proxy_object("org.bluez", device_path, introspection)

    # Gather all battery services
    battery_services = []
    for svc_path in device.child_paths:
        svc_introspection = await bus.introspect("org.bluez", svc_path)
        svc_proxy = bus.get_proxy_object("org.bluez", svc_path, svc_introspection)
        svc_props = svc_proxy.get_interface("org.freedesktop.DBus.Properties")

        svc_uuid = (
            await svc_props.call_get("org.bluez.GattService1", "UUID")
        ).value.lower()
        if svc_uuid == BATTERY_SERVICE_UUID:
            battery_services.append(svc_path)

    if not battery_services:
        print("No Battery Services found!")
        return

    # Load previous state
    previous_state = load_previous_state()
    current_state = {}

    # Read battery levels
    for idx, svc_path in enumerate(battery_services):
        label = "primary" if idx == 0 else f"secondary_{idx}"
        level = await read_battery_service(bus, svc_path)
        current_state[label] = level

        prev = previous_state.get(label, 100)  # assume full if missing

        if level < prev and level < THRESHOLD:
            notify(f"{label.capitalize()} battery low: {level}%")

        print(f"{label.capitalize()} Battery: {level}% (previous: {prev}%)")

    # Save current state
    save_current_state(current_state)


asyncio.run(main())

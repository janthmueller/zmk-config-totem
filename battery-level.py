#!/usr/bin/env python3
import asyncio

from dbus_next.aio import MessageBus
from dbus_next.constants import BusType

BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
TARGET_NAME = "Totem"  # substring to identify your keyboard


async def find_totem_device(bus):
    # Get the root ObjectManager for BlueZ
    root_introspection = await bus.introspect("org.bluez", "/")
    root_obj = bus.get_proxy_object("org.bluez", "/", root_introspection)
    manager = root_obj.get_interface("org.freedesktop.DBus.ObjectManager")

    # Get all managed objects
    objects = await manager.call_get_managed_objects()

    for path, interfaces in objects.items():
        dev = interfaces.get("org.bluez.Device1")
        if dev:
            name_variant = dev.get("Name") or dev.get("Alias")
            if name_variant:
                name = name_variant.value  # <-- Fix: access Variant.value
                if TARGET_NAME.lower() in name.lower():
                    return path
    return None


async def read_battery_service(bus, svc_path, label):
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
        print(f"{label} Battery Level: {battery_level}%")


async def main():
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    device_path = await find_totem_device(bus)

    if not device_path:
        print("Totem keyboard not found!")
        return

    print(f"Found Totem at {device_path}")

    introspection = await bus.introspect("org.bluez", device_path)
    device = bus.get_proxy_object("org.bluez", device_path, introspection)

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

    for idx, svc_path in enumerate(battery_services):
        label = "Primary" if idx == 0 else f"Secondary {idx}"
        await read_battery_service(bus, svc_path, label)


asyncio.run(main())


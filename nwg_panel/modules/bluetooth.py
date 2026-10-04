"""BlueZ adapter and device controls without a tray applet or command polling."""

from gi.repository import Gio, GLib

from nwg_panel.modules.connectivity import ConnectivitySection
from nwg_panel.modules.bluetooth_agent import get_agent


class Bluetooth(ConnectivitySection):
    def __init__(self):
        super().__init__("Bluetooth", "bluetooth-active-symbolic")
        self.bus = None
        self.agent = None
        self.subscriptions = []
        self.objects = {}
        self.adapter_ids = []
        self.discovery_path = None
        self.scan_request = None
        self.scan_generation = 0
        self.discovery_timer = 0
        self.loading = False
        self.reload = False
        self.adapter.connect("changed", self.on_adapter_changed)
        self.expander.connect("notify::expanded", self.on_expanded)
        Gio.bus_get(Gio.BusType.SYSTEM, self.cancellable, self.on_bus_ready, None)

    def on_bus_ready(self, source, result, data):
        if self.cancellable.is_cancelled():
            return
        try:
            self.bus = Gio.bus_get_finish(result)
        except GLib.Error:
            return
        self.agent = get_agent(self.bus)
        for interface, member in (("org.freedesktop.DBus.Properties", "PropertiesChanged"),
                                  ("org.freedesktop.DBus.ObjectManager", "InterfacesAdded"),
                                  ("org.freedesktop.DBus.ObjectManager", "InterfacesRemoved")):
            self.subscriptions.append(self.bus.signal_subscribe(
                "org.bluez", interface, member, None, None,
                Gio.DBusSignalFlags.NONE, self.schedule_refresh))
        self.subscriptions.append(self.bus.signal_subscribe(
            "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
            "/org/freedesktop/DBus", "org.bluez", Gio.DBusSignalFlags.NONE, self.schedule_refresh))
        self.sync()

    def call(self, path, interface, method, parameters, callback=None, failure=None, timeout=10000):
        def finished(bus, result, data):
            try:
                reply = bus.call_finish(result)
                error = None
            except GLib.Error as caught:
                reply, error = None, caught
            if self.cancellable.is_cancelled():
                return
            if error:
                (failure or self.on_error)(error)
            elif callback:
                callback(reply.unpack() if reply else ())
        self.bus.call("org.bluez", path, interface, method, parameters, None,
                      Gio.DBusCallFlags.NO_AUTO_START | Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION,
                      timeout, self.cancellable, finished, None)

    def set_property(self, path, interface, name, value, callback=None):
        self.call(path, "org.freedesktop.DBus.Properties", "Set",
                  GLib.Variant("(ssv)", (interface, name, value)), callback or self.on_action_finished)

    def on_error(self, error):
        self.set_busy(False)
        self.show_message(error.message)
        self.schedule_refresh()

    def on_action_finished(self, reply):
        self.set_busy(False)
        self.show_message("")
        self.schedule_refresh()

    def sync(self):
        if not self.bus:
            return
        if self.loading:
            self.reload = True
            return
        self.loading = True
        self.call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects", None,
                  self.on_objects, self.on_unavailable)

    def on_unavailable(self, error):
        self.loading = False
        self.reload = False
        self.objects = {}
        self.hide()

    def on_objects(self, reply):
        self.loading = False
        self.objects = reply[0]
        self.render()
        if self.reload:
            self.reload = False
            self.schedule_refresh()

    def selected_adapter(self):
        selected = self.adapter.get_active_id()
        return selected if selected in self.adapter_ids else self.adapter_ids[0] if self.adapter_ids else None

    def render(self):
        adapters = {path: interfaces["org.bluez.Adapter1"] for path, interfaces in self.objects.items()
                    if "org.bluez.Adapter1" in interfaces}
        ids = sorted(adapters)
        if not ids:
            self.hide()
            return
        self.show()
        if ids != self.adapter_ids:
            current = self.adapter.get_active_id()
            self.adapter.remove_all()
            for path in ids:
                self.adapter.append(path, adapters[path].get("Alias", path.rsplit("/", 1)[-1]))
            self.adapter_ids = ids
            self.adapter.set_active_id(current if current in ids else ids[0])
        self.adapter.set_visible(len(ids) > 1)
        adapter = self.selected_adapter()
        powered = adapters[adapter].get("Powered", False)
        self.updating = True
        self.power.set_active(powered)
        self.updating = False
        self.scan_button.set_sensitive(powered)
        self.scan_button.set_label("Stop scan" if self.discovery_path else "Scan")
        devices = [(path, interfaces["org.bluez.Device1"]) for path, interfaces in self.objects.items()
                   if "org.bluez.Device1" in interfaces and interfaces["org.bluez.Device1"].get("Adapter") == adapter]
        devices.sort(key=lambda item: (not item[1].get("Connected", False),
                                      not item[1].get("Paired", False), item[1].get("Alias", "").casefold()))
        connected = [properties.get("Alias", "Device") for path, properties in devices
                     if properties.get("Connected")]
        self.label.set_text((", ".join(connected) if connected else "On" if powered else "Off"))
        self.clear_rows()
        if powered:
            for path, properties in devices:
                connected = properties.get("Connected", False)
                paired = properties.get("Paired", False)
                name = properties.get("Alias") or properties.get("Name") or properties.get("Address", "Device")
                text = name + (" · Connected" if connected else " · Paired" if paired else "")
                self.add_row(text, "Disconnect" if connected else "Connect" if paired else "Pair",
                             lambda path=path, connected=connected, paired=paired:
                             self.device_action(path, connected, paired))
            if not devices:
                self.add_row("No devices found. Select Scan to search.")
        self.rows.show_all()

    def set_power(self, enabled):
        adapter = self.selected_adapter()
        if adapter:
            if not enabled:
                self.stop_scan()
                self.agent.cancel(self)
            self.set_busy(True)
            self.set_property(adapter, "org.bluez.Adapter1", "Powered", GLib.Variant("b", enabled))

    def scan(self, *args):
        if self.busy:
            return
        if self.discovery_path:
            self.stop_scan()
            return
        adapter = self.selected_adapter()
        if not adapter:
            return
        self.set_busy(True)
        generation = self.scan_generation
        self.scan_request = adapter
        def started(reply):
            self.scan_request = None
            self.discovery_path = adapter
            if generation != self.scan_generation:
                self.stop_scan()
            else:
                self.discovery_timer = GLib.timeout_add_seconds(30, self.stop_scan)
            self.on_action_finished(reply)
        def failed(error):
            self.scan_request = None
            self.on_error(error)
        self.call(adapter, "org.bluez.Adapter1", "StartDiscovery", None, started, failed)

    def stop_scan(self):
        self.scan_generation += 1
        if self.discovery_timer:
            GLib.source_remove(self.discovery_timer)
            self.discovery_timer = 0
        path = self.discovery_path or self.scan_request
        self.discovery_path = self.scan_request = None
        if path and self.bus:
            # Cleanup must survive widget cancellation; release only our discovery session.
            self.bus.call("org.bluez", path, "org.bluez.Adapter1", "StopDiscovery", None, None,
                          Gio.DBusCallFlags.NO_AUTO_START, 5000, None, None, None)
            self.schedule_refresh()
        return False

    def device_action(self, path, connected, paired):
        if self.busy:
            return
        self.stop_scan()
        if connected:
            self.set_busy(True)
            self.call(path, "org.bluez.Device1", "Disconnect", None, self.on_action_finished)
        elif paired:
            self.connect_device(path)
        else:
            self.agent.pair(self, path)

    def connect_device(self, path):
        self.set_busy(True)
        self.show_message("Connecting…")
        self.call(path, "org.bluez.Device1", "Connect", None, self.on_action_finished, timeout=30000)

    def on_adapter_changed(self, *args):
        self.stop_scan()
        self.schedule_refresh()

    def on_expanded(self, *args):
        if not self.expander.get_expanded():
            self.stop_scan()
            if self.agent:
                self.agent.cancel(self)

    def on_unmap(self, *args):
        self.stop_scan()
        if self.agent:
            self.agent.cancel(self)
        super().on_unmap(*args)

    def on_destroy(self, *args):
        self.on_unmap()
        if self.bus:
            for subscription in self.subscriptions:
                self.bus.signal_unsubscribe(subscription)
        super().on_destroy(*args)

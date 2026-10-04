"""Native NetworkManager controls; libnm owns the asynchronous D-Bus cache."""

import gi
from gi.repository import GLib, GObject

from nwg_panel.modules.connectivity import ConnectivitySection
from nwg_panel.modules.wifi_utils import security, select_access_points, valid_password


class Network(ConnectivitySection):
    def __init__(self):
        super().__init__("Wi-Fi", "network-wireless-symbolic")
        self.client = None
        self.devices = []
        self.wired = []
        self.device_handlers = []
        self.adapter_ids = []
        self.toolbar.set_no_show_all(True)
        self.adapter.connect("changed", self.schedule_refresh)
        try:
            gi.require_version("NM", "1.0")
            from gi.repository import NM
            self.NM = NM
        except (ValueError, ImportError):
            return
        NM.Client.new_async(self.cancellable, self.on_client_ready, None)

    def on_client_ready(self, source, result, data):
        if self.cancellable.is_cancelled():
            return
        try:
            self.client = self.NM.Client.new_finish(result)
        except GLib.Error:
            return
        self.watch(self.client, "notify", self.on_client_changed)
        self.watch(self.client, "device-added", self.on_devices_changed)
        self.watch(self.client, "device-removed", self.on_devices_changed)
        self.on_devices_changed()

    def on_client_changed(self, client, property):
        if property.name in ("nm-running", "wireless-enabled", "wireless-hardware-enabled", "devices", "connections"):
            self.on_devices_changed()

    def on_devices_changed(self, *args):
        for obj, handler in self.device_handlers:
            GObject.Object.disconnect(obj, handler)
        self.device_handlers = []
        self.devices = [device for device in self.client.get_devices()
                        if isinstance(device, self.NM.DeviceWifi) and device.get_managed()]
        self.wired = [device for device in self.client.get_devices()
                      if device.get_device_type() == self.NM.DeviceType.ETHERNET and device.get_managed()]
        for device in self.devices + self.wired:
            self.device_handlers.append((device, device.connect("notify", self.schedule_refresh)))
            if device in self.wired:
                continue
            for signal in ("access-point-added", "access-point-removed"):
                self.device_handlers.append((device, device.connect(signal, self.on_devices_changed)))
            for ap in device.get_access_points():
                self.device_handlers.append((ap, ap.connect("notify", self.schedule_refresh)))
        self.schedule_refresh()

    def selected_device(self):
        selected = self.adapter.get_active_id()
        return next((device for device in self.devices if device.get_path() == selected),
                    self.devices[0] if self.devices else None)

    def sync(self):
        if not self.client or not self.client.get_nm_running() or not (self.devices or self.wired):
            self.hide()
            return
        self.show()
        self.toolbar.set_visible(bool(self.devices))
        self.clear_rows()
        if not self.devices:
            self.label.set_text("Network: " + ("Ethernet connected" if any(
                device.get_state() == self.NM.DeviceState.ACTIVATED for device in self.wired) else "Not connected"))
            self.add_wired_rows()
            self.rows.show_all()
            return
        ids = [device.get_path() for device in self.devices]
        if ids != self.adapter_ids:
            current = self.adapter.get_active_id()
            self.adapter.remove_all()
            for device in self.devices:
                self.adapter.append(device.get_path(), device.get_iface())
            self.adapter.set_active_id(current if current in ids else ids[0])
            self.adapter_ids = ids
        self.adapter.set_visible(len(ids) > 1)
        self.updating = True
        self.power.set_active(self.client.wireless_get_enabled())
        self.updating = False
        hardware = self.client.wireless_hardware_get_enabled()
        self.power.set_sensitive(hardware)
        self.scan_button.set_sensitive(hardware and self.client.wireless_get_enabled())
        device = self.selected_device()
        active = device.get_active_access_point()
        activated = device.get_state() == self.NM.DeviceState.ACTIVATED
        self.label.set_text((self.ssid(active).decode("utf-8", "replace") if active else
                                        "Not connected" if self.client.wireless_get_enabled() else "Off"))
        if not hardware:
            self.add_row("Wi-Fi is blocked by a hardware switch")
        elif self.client.wireless_get_enabled():
            points = []
            for ap in device.get_access_points():
                points.append({"ssid": self.ssid(ap), "security": security(int(ap.get_flags()),
                               int(ap.get_wpa_flags()), int(ap.get_rsn_flags())),
                               "strength": ap.get_strength(), "active": activated and ap == active,
                               "device": device.get_path(), "ap": ap})
            for point in select_access_points(points):
                text = "{}  {}%{}".format(point["ssid"].decode("utf-8", "replace"), point["strength"],
                                          " · Connected" if point["active"] else
                                          " · Secured" if point["security"] != "open" else "")
                connecting = self.NM.DeviceState.PREPARE <= device.get_state() < self.NM.DeviceState.ACTIVATED
                self.add_row(text, "Disconnect" if point["active"] else "Connect",
                             lambda point=point: self.connect_network(device, point), not connecting)
            if not points:
                self.add_row("No networks found. Select Scan to search.")
        self.add_wired_rows()
        if device.get_state() == self.NM.DeviceState.FAILED:
            self.show_message("Connection failed: " + device.get_state_reason().value_nick.replace("-", " "))
        elif self.NM.DeviceState.PREPARE <= device.get_state() < self.NM.DeviceState.ACTIVATED:
            self.show_message("Connecting…")
        self.rows.show_all()

    def add_wired_rows(self):
        for wired in self.wired:
            connected = wired.get_state() == self.NM.DeviceState.ACTIVATED
            self.add_row("Ethernet ({}): {}".format(wired.get_iface(),
                         "Connected" if connected else "Disconnected"),
                         "Disconnect" if connected else None,
                         lambda device=wired: self.disconnect_device(device))

    def disconnect_device(self, device):
        if not self.busy:
            self.set_busy(True)
            device.disconnect_async(self.cancellable, self.finish, "disconnect_finish")

    @staticmethod
    def ssid(ap):
        value = ap.get_ssid() if ap else None
        return bytes(value.get_data()) if value else b""

    def finish(self, source, result, finish_method):
        if self.cancellable.is_cancelled():
            return
        self.set_busy(False)
        try:
            getattr(source, finish_method)(result)
            self.show_message("")
        except GLib.Error as error:
            self.show_message(error.message)
        self.on_devices_changed()

    def set_power(self, enabled):
        self.cancel_prompt()
        self.set_busy(True)
        self.client.dbus_set_property(
            "/org/freedesktop/NetworkManager", "org.freedesktop.NetworkManager", "WirelessEnabled",
            GLib.Variant("b", enabled), 5000, self.cancellable, self.finish, "dbus_set_property_finish")

    def scan(self, *args):
        device = self.selected_device()
        if not device or self.busy:
            return
        self.set_busy(True)
        self.show_message("Scanning…")
        device.request_scan_async(self.cancellable, self.finish, "request_scan_finish")

    def connect_network(self, device, point):
        if self.busy:
            return
        if point["active"]:
            self.disconnect_device(device)
            return
        saved = [connection for connection in self.client.get_connections()
                 if device.connection_valid(connection) and point["ap"].connection_valid(connection)]
        if saved:
            connection = max(saved, key=lambda conn: conn.get_setting_connection().get_timestamp())
            self.activate_saved(connection, device, point)
            return
        mode = point["security"]
        if mode in ("enterprise", "wep", "unsupported"):
            self.show_message("Configure this network's authentication in a NetworkManager settings editor first.")
        elif mode in ("sae", "wpa-psk"):
            self.ask("Password for " + point["ssid"].decode("utf-8", "replace"),
                     lambda password: self.add_network(device, point, password) if password is not None else None,
                     entry=True, secret=True)
        else:
            self.add_network(device, point)

    def activate_saved(self, connection, device, point):
        if point["security"] not in ("sae", "wpa-psk"):
            self.activate(connection, device, point)
            return
        self.set_busy(True)
        generation = self.interaction_generation
        def secrets_ready(source, result, data):
            if self.cancellable.is_cancelled():
                return
            if generation != self.interaction_generation:
                self.set_busy(False)
                return
            try:
                secrets = source.get_secrets_finish(result).unpack()
            except GLib.Error:
                secrets = {}
            reasons = self.NM.DeviceStateReason
            authentication_failed = (device.get_state() == self.NM.DeviceState.FAILED and
                                     device.get_state_reason() in (
                                         reasons.NO_SECRETS, reasons.SUPPLICANT_DISCONNECT,
                                         reasons.SUPPLICANT_CONFIG_FAILED, reasons.SUPPLICANT_FAILED,
                                         reasons.SUPPLICANT_TIMEOUT))
            if secrets.get("802-11-wireless-security", {}).get("psk") and not authentication_failed:
                self.activate(connection, device, point)
            else:
                self.set_busy(False)
                self.ask("Password for " + point["ssid"].decode("utf-8", "replace"),
                         lambda password: self.save_password(connection, device, point, password)
                         if password is not None else None, entry=True, secret=True)
        connection.get_secrets_async("802-11-wireless-security", self.cancellable, secrets_ready, None)

    def activate(self, connection, device, point):
        self.set_busy(True)
        self.client.activate_connection_async(connection, device, point["ap"].get_path(),
                                              self.cancellable, self.finish, "activate_connection_finish")

    def save_password(self, connection, device, point, password):
        if not valid_password(password, point["security"]):
            self.show_message("Invalid Wi-Fi password length or format. Select Connect to try again.")
            return
        updated = self.NM.SimpleConnection.new_clone(connection)
        authentication = updated.get_setting_wireless_security()
        authentication.props.psk = password
        authentication.props.psk_flags = self.NM.SettingSecretFlags.NONE
        self.set_busy(True)
        def saved(source, result, data):
            if self.cancellable.is_cancelled():
                return
            try:
                source.update2_finish(result)
            except GLib.Error as error:
                self.set_busy(False)
                self.show_message(error.message)
                return
            self.activate(connection, device, point)
        connection.update2(updated.to_dbus(self.NM.ConnectionSerializationFlags.ALL),
                           self.NM.SettingsUpdate2Flags.TO_DISK, GLib.Variant("a{sv}", {}),
                           self.cancellable, saved, None)

    def add_network(self, device, point, password=None):
        mode = point["security"]
        if mode in ("sae", "wpa-psk") and not valid_password(password or "", mode):
            self.show_message("Invalid Wi-Fi password length or format. Select Connect to try again.")
            return
        NM = self.NM
        connection = NM.SimpleConnection.new()
        general = NM.SettingConnection.new()
        general.props.id = point["ssid"].decode("utf-8", "replace")
        general.props.uuid = GLib.uuid_string_random()
        general.props.type = "802-11-wireless"
        wireless = NM.SettingWireless.new()
        wireless.props.ssid = GLib.Bytes.new(point["ssid"])
        wireless.props.mode = "infrastructure"
        connection.add_setting(general)
        connection.add_setting(wireless)
        if mode != "open":
            authentication = NM.SettingWirelessSecurity.new()
            authentication.props.key_mgmt = mode
            if password is not None:
                authentication.props.psk = password
            connection.add_setting(authentication)
        ipv4 = NM.SettingIP4Config.new()
        ipv4.props.method = "auto"
        ipv6 = NM.SettingIP6Config.new()
        ipv6.props.method = "auto"
        connection.add_setting(ipv4)
        connection.add_setting(ipv6)
        self.set_busy(True)
        self.client.add_and_activate_connection_async(connection, device, point["ap"].get_path(),
                                                      self.cancellable, self.finish,
                                                      "add_and_activate_connection_finish")

    def on_destroy(self, *args):
        for obj, handler in self.device_handlers:
            GObject.Object.disconnect(obj, handler)
        self.device_handlers = []
        super().on_destroy(*args)

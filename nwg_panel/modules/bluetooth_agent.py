"""BlueZ pairing agent shared by all panels in this process.

The agent is registered for our own pairing requests only. It never replaces
another application's default agent or silently authorizes incoming devices.
"""

from gi.repository import Gio, GLib


AGENT_XML = """
<node><interface name="org.bluez.Agent1">
  <method name="Release"/>
  <method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
  <method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
  <method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
  <method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
  <method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
  <method name="RequestAuthorization"><arg type="o" direction="in"/></method>
  <method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
  <method name="Cancel"/>
</interface></node>
"""


class BluetoothAgent:
    path = "/org/nwg_panel/BluetoothAgent"

    def __init__(self, bus):
        self.bus = bus
        self.owner = None
        self.device = None
        self.registered = False
        self.invocation = None
        self.generation = 0
        self.sender = None
        self.node = Gio.DBusNodeInfo.new_for_xml(AGENT_XML)
        self.registration = bus.register_object(self.path, self.node.interfaces[0], self.on_method, None, None)
        self.watch = bus.signal_subscribe(
            "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
            "/org/freedesktop/DBus", "org.bluez", Gio.DBusSignalFlags.NONE, self.on_owner_changed)

    def on_owner_changed(self, *args):
        self.registered = False
        self.sender = None
        self.cancel()

    def pair(self, section, device):
        if self.owner:
            section.show_message("Another Bluetooth pairing request is already in progress.")
            return
        self.owner, self.device = section, device
        self.generation += 1
        generation = self.generation
        section.set_busy(True)
        section.show_message("Pairing…")
        def named(bus, result, data):
            try:
                sender = bus.call_finish(result).unpack()[0]
            except GLib.Error as error:
                if generation == self.generation:
                    self.on_registration_error(error)
                return
            if generation != self.generation:
                return
            self.sender = sender
            if self.registered:
                self.start_pair()
            else:
                section.call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                             GLib.Variant("(os)", (self.path, "KeyboardDisplay")),
                             lambda result: self.on_registered(result, generation, sender),
                             lambda error: self.on_registration_error(error)
                             if generation == self.generation else None)
        self.bus.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetNameOwner",
                      GLib.Variant("(s)", ("org.bluez",)), None, Gio.DBusCallFlags.NONE, 5000,
                      section.cancellable, named, None)

    def on_registered(self, result, generation, sender):
        if sender != self.sender:
            return
        self.registered = True
        if generation == self.generation:
            self.start_pair()

    def on_registration_error(self, error):
        if Gio.DBusError.get_remote_error(error) == "org.bluez.Error.AlreadyExists":
            # A cancelled request may have completed registration before its
            # callback ran. All our panels share this one agent and bus name.
            self.registered = True
            self.start_pair()
            return
        owner = self.owner
        self.owner = self.device = None
        if owner:
            owner.set_busy(False)
            owner.show_message(error.message)

    def start_pair(self):
        if self.owner:
            generation = self.generation
            self.owner.call(self.device, "org.bluez.Device1", "Pair", None,
                            lambda result: self.on_paired(result) if generation == self.generation else None,
                            lambda error: self.on_pair_error(error) if generation == self.generation else None,
                            timeout=120000)

    def on_paired(self, result):
        owner, device = self.owner, self.device
        self.owner = self.device = None
        if not owner:
            return
        owner.cancel_prompt()
        owner.set_property(device, "org.bluez.Device1", "Trusted", GLib.Variant("b", True),
                           lambda result: owner.connect_device(device))

    def on_pair_error(self, error):
        owner = self.owner
        device = self.device
        self.owner = self.device = None
        if owner:
            owner.cancel_prompt()
            owner.set_busy(False)
            owner.show_message(error.message)
            owner.call(device, "org.bluez.Device1", "CancelPairing", None,
                       lambda result: None, lambda error: None)
            owner.schedule_refresh()

    def reject(self):
        if self.invocation:
            self.invocation.return_dbus_error("org.bluez.Error.Rejected", "Pairing cancelled")
            self.invocation = None

    def cancel(self, section=None):
        if section is not None and section is not self.owner:
            return
        owner, device = self.owner, self.device
        self.owner = self.device = None
        self.generation += 1
        self.reject()
        if owner:
            owner.cancel_prompt()
            owner.set_busy(False)
            owner.call(device, "org.bluez.Device1", "CancelPairing", None,
                       lambda result: None, lambda error: None)

    def answer(self, value, method):
        invocation, self.invocation = self.invocation, None
        if invocation is None:
            return
        if value is None:
            invocation.return_dbus_error("org.bluez.Error.Rejected", "Pairing cancelled")
            self.cancel()
        elif method == "RequestPinCode":
            if not value or len(value) > 16:
                invocation.return_dbus_error("org.bluez.Error.Rejected", "Invalid PIN")
            else:
                invocation.return_value(GLib.Variant("(s)", (value,)))
        elif method == "RequestPasskey":
            if not value.isascii() or not value.isdigit() or len(value) > 6:
                invocation.return_dbus_error("org.bluez.Error.Rejected", "Invalid passkey")
            else:
                invocation.return_value(GLib.Variant("(u)", (int(value),)))
        else:
            invocation.return_value(None)

    def on_method(self, bus, sender, path, interface, method, parameters, invocation):
        if sender != self.sender:
            invocation.return_dbus_error("org.bluez.Error.Rejected", "Only BlueZ may request pairing authorization")
            return
        if method in ("Release", "Cancel"):
            if method == "Release":
                self.registered = False
            self.cancel()
            invocation.return_value(None)
            return
        args = parameters.unpack()
        if not self.owner or not args or args[0] != self.device:
            invocation.return_dbus_error("org.bluez.Error.Rejected", "No pairing request for this device")
            return
        if method in ("DisplayPinCode", "DisplayPasskey"):
            code = args[1] if method == "DisplayPinCode" else "{:06d}".format(args[1])
            self.owner.show_message("Enter {} on the Bluetooth device.".format(code))
            invocation.return_value(None)
            return
        if self.invocation:
            invocation.return_dbus_error("org.bluez.Error.Rejected", "Another prompt is pending")
            return
        text = {"RequestPinCode": "Enter the device's PIN:",
                "RequestPasskey": "Enter the device's six-digit passkey:",
                "RequestAuthorization": "Allow pairing with this device?",
                "AuthorizeService": "Allow this device to connect?"}.get(method)
        if method == "RequestConfirmation":
            text = "Does code {:06d} match the code on your device?".format(args[1])
        if text is None:
            invocation.return_dbus_error("org.bluez.Error.Rejected", "Unsupported pairing request")
            return
        # Cancel any old prompt before storing the new invocation.
        self.owner.cancel_prompt()
        self.invocation = invocation
        self.owner.ask(text, lambda value: self.answer(value, method),
                       entry=method in ("RequestPinCode", "RequestPasskey"))


_agent = None


def get_agent(bus):
    global _agent
    if _agent is None:
        _agent = BluetoothAgent(bus)
    return _agent

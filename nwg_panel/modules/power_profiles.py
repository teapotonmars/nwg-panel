"""Power mode selector for the controls popup, backed by power-profiles-daemon."""

from gi.repository import Gio, GLib, Gtk


PROFILES = {
    "performance": ("Performance", "power-profile-performance-symbolic"),
    "balanced": ("Balanced", "power-profile-balanced-symbolic"),
    "power-saver": ("Power Saver", "power-profile-power-saver-symbolic"),
}
SERVICES = (
    ("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles"),
    ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles"),
)


class PowerProfiles(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_no_show_all(True)
        self.proxy = None
        self.buttons = {}
        self.updating = False
        self.pending = False
        self.cancellable = Gio.Cancellable()
        self.handlers = []

        self.icon = Gtk.Image()
        self.label = Gtk.Label(label="Power Mode")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.pack_start(self.icon, False, False, 0)
        header.pack_start(self.label, False, False, 0)
        self.expander = Gtk.Expander()
        self.expander.set_label_widget(header)
        self.choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.expander.add(self.choices)
        self.pack_start(self.expander, False, False, 6)
        self.error = Gtk.Label(xalign=0)
        self.error.set_line_wrap(True)
        self.error.set_no_show_all(True)
        self.pack_start(self.error, False, False, 0)
        self.expander.show_all()
        self.connect("destroy", self.on_destroy)
        self.connect_service(0)

    def connect_service(self, index):
        name, path = SERVICES[index]
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SYSTEM, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
            name, path, name, self.cancellable, self.on_proxy_ready, index)

    def on_proxy_ready(self, source, result, index):
        if self.cancellable.is_cancelled():
            return
        try:
            proxy = Gio.DBusProxy.new_for_bus_finish(result)
        except GLib.Error:
            proxy = None
        if (proxy is None or not proxy.get_name_owner()) and index + 1 < len(SERVICES):
            self.connect_service(index + 1)
            return
        if proxy is None:
            return
        self.proxy = proxy
        self.handlers = [proxy.connect("g-properties-changed", self.sync),
                         proxy.connect("notify::g-name-owner", self.sync)]
        self.sync()

    def property(self, name, default):
        value = self.proxy.get_cached_property(name)
        return value.unpack() if value is not None else default

    def sync(self, *args):
        if not self.proxy or not self.proxy.get_name_owner():
            self.hide()
            return
        profiles = {item.get("Profile") for item in self.property("Profiles", [])}
        available = [profile for profile in PROFILES if profile in profiles]
        self.updating = True
        if list(self.buttons) != available:
            for child in self.choices.get_children():
                child.destroy()
            self.buttons = {}
            group = None
            for profile in available:
                button = Gtk.RadioButton.new_with_label_from_widget(group, PROFILES[profile][0])
                group = button
                button.connect("toggled", self.on_selected, profile)
                self.choices.pack_start(button, False, False, 0)
                self.buttons[profile] = button
            self.choices.show_all()
        active = self.property("ActiveProfile", "")
        label, icon = PROFILES.get(active, ("Custom", "gnome-power-manager-symbolic"))
        self.label.set_text("Power Mode: " + label)
        self.icon.set_from_icon_name(icon, Gtk.IconSize.MENU)
        self.updating = True
        try:
            for profile, button in self.buttons.items():
                button.set_active(profile == active)
        finally:
            self.updating = False
        self.expander.set_sensitive(bool(available) and not self.pending)
        self.set_visible(bool(available))

    def on_selected(self, button, profile):
        if self.updating or self.pending or not button.get_active():
            return
        if profile == self.property("ActiveProfile", ""):
            return
        self.pending = True
        self.expander.set_sensitive(False)
        self.error.hide()
        interface = self.proxy.get_interface_name()
        self.proxy.call(
            "org.freedesktop.DBus.Properties.Set",
            GLib.Variant("(ssv)", (interface, "ActiveProfile", GLib.Variant("s", profile))),
            Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 5000,
            self.cancellable, self.on_set_finished, None)

    def on_set_finished(self, proxy, result, data):
        if self.cancellable.is_cancelled():
            return
        self.pending = False
        try:
            proxy.call_finish(result)
        except GLib.Error as error:
            self.error.set_text("Could not change power mode: " + error.message)
            self.error.show()
        self.sync()

    def on_destroy(self, *args):
        self.cancellable.cancel()
        if self.proxy:
            for handler in self.handlers:
                self.proxy.disconnect(handler)

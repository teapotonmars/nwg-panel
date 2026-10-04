import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class MockBox:
    def __init__(self, **kwargs):
        self.get_children = Mock(return_value=[])

    def __getattr__(self, name):
        value = Mock()
        setattr(self, name, value)
        return value


class DBusError(Exception):
    def __init__(self, message):
        self.message = message


class PowerProfilesTests(unittest.TestCase):
    def setUp(self):
        self.gio = Mock()
        self.gio.Cancellable.return_value.is_cancelled.return_value = False
        self.gtk = SimpleNamespace(Box=MockBox, Image=Mock(side_effect=Mock),
                                   Label=Mock(side_effect=Mock), Expander=Mock(side_effect=Mock),
                                   RadioButton=Mock(), Orientation=SimpleNamespace(VERTICAL=1, HORIZONTAL=0),
                                   IconSize=SimpleNamespace(MENU=0))
        self.gtk.RadioButton.new_with_label_from_widget.side_effect = lambda *args: Mock()
        glib = SimpleNamespace(Error=DBusError, Variant=lambda signature, value: (signature, value))
        spec = importlib.util.spec_from_file_location(
            "tested_power_profiles", Path("nwg_panel/modules/power_profiles.py"))
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"gi": Mock(), "gi.repository": SimpleNamespace(
                Gio=self.gio, GLib=glib, Gtk=self.gtk)}):
            spec.loader.exec_module(module)
        self.widget = module.PowerProfiles()
        self.proxy = Mock()
        self.proxy.get_name_owner.return_value = ":1.42"
        self.proxy.get_interface_name.return_value = "org.freedesktop.UPower.PowerProfiles"
        self.properties = {"Profiles": [{"Profile": "balanced"}, {"Profile": "power-saver"}],
                           "ActiveProfile": "balanced"}
        self.proxy.get_cached_property.side_effect = lambda name: SimpleNamespace(
            unpack=lambda: self.properties[name]) if name in self.properties else None
        self.gio.DBusProxy.new_for_bus_finish.return_value = self.proxy
        self.widget.on_proxy_ready(None, Mock(), 0)

    def test_only_supported_modes_and_active_label(self):
        self.assertEqual(list(self.widget.buttons), ["balanced", "power-saver"])
        self.widget.label.set_text.assert_called_with("Power Mode: Balanced")
        self.widget.buttons["balanced"].set_active.assert_called_with(True)
        self.proxy.call.assert_not_called()

    def test_external_changes_update_selection(self):
        self.properties["ActiveProfile"] = "power-saver"
        self.widget.sync()
        self.widget.label.set_text.assert_called_with("Power Mode: Power Saver")
        self.widget.buttons["power-saver"].set_active.assert_called_with(True)
        self.proxy.call.assert_not_called()

    def test_selection_sets_property_asynchronously_and_prevents_repeat(self):
        button = self.widget.buttons["power-saver"]
        button.get_active.return_value = True
        self.widget.on_selected(button, "power-saver")
        self.widget.on_selected(button, "power-saver")
        self.proxy.call.assert_called_once()
        arguments = self.proxy.call.call_args.args
        self.assertEqual(arguments[0], "org.freedesktop.DBus.Properties.Set")
        self.assertEqual(arguments[1], ("(ssv)", ("org.freedesktop.UPower.PowerProfiles",
                                               "ActiveProfile", ("s", "power-saver"))))
        self.assertTrue(self.widget.pending)
        self.widget.expander.set_sensitive.assert_called_with(False)

    def test_failed_change_shows_error_and_restores_selection(self):
        self.proxy.call_finish.side_effect = DBusError("Permission denied")
        self.widget.pending = True
        self.widget.on_set_finished(self.proxy, Mock(), None)
        self.widget.error.set_text.assert_called_with("Could not change power mode: Permission denied")
        self.widget.error.show.assert_called_once()
        self.assertFalse(self.widget.pending)
        self.widget.buttons["balanced"].set_active.assert_called_with(True)

    def test_programmatic_updates_do_not_change_profile(self):
        self.widget.updating = True
        self.widget.on_selected(self.widget.buttons["power-saver"], "power-saver")
        self.proxy.call.assert_not_called()

    def test_service_disappearance_hides_selector(self):
        self.proxy.get_name_owner.return_value = None
        self.widget.sync()
        self.widget.hide.assert_called_once()

    def test_legacy_service_fallback(self):
        self.proxy.get_name_owner.return_value = None
        self.widget.on_proxy_ready(None, Mock(), 0)
        self.assertEqual(self.gio.DBusProxy.new_for_bus.call_args.args[3:6],
                         ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles"))

    def test_unavailable_service_is_watched_for_later_start(self):
        self.proxy.get_name_owner.return_value = None
        self.widget.on_proxy_ready(None, Mock(), 1)
        self.widget.hide.assert_called_once()
        self.proxy.get_name_owner.return_value = ":1.43"
        self.widget.sync()
        self.widget.set_visible.assert_called_with(True)

    def test_destroy_cancels_requests_and_disconnects_signals(self):
        self.widget.on_destroy()
        self.widget.cancellable.cancel.assert_called_once()
        self.assertEqual(self.proxy.disconnect.call_count, 2)


if __name__ == "__main__":
    unittest.main()

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from nwg_panel.modules.wifi_utils import security, select_access_points, valid_password


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


def load(name, repository, dependencies=None):
    spec = importlib.util.spec_from_file_location("tested_" + name, Path("nwg_panel/modules") / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"gi": SimpleNamespace(require_version=lambda *args: None),
                                 "gi.repository": repository, **(dependencies or {})}):
        spec.loader.exec_module(module)
    return module


class WifiIdentityTests(unittest.TestCase):
    def test_security_modes(self):
        for flags, wpa, rsn, expected in [(0, 0, 0, "open"), (1, 0, 0, "wep"),
                                         (1, 0x100, 0, "wpa-psk"), (1, 0, 0x400, "sae"),
                                         (1, 0, 0x500, "sae"), (1, 0, 0x200, "enterprise"),
                                         (1, 0, 0x2000, "enterprise"), (0, 0, 0x800, "owe"),
                                         (0, 0, 0x10000, "unsupported")]:
            with self.subTest(expected=expected):
                self.assertEqual(security(flags, wpa, rsn), expected)

    def test_active_bssid_is_preferred_and_security_and_adapter_stay_distinct(self):
        def point(ssid, strength, active=False, mode="open", device="wifi0"):
            return dict(ssid=ssid, strength=strength, active=active, security=mode, device=device)
        active = point(b"Home", 40, True)
        encrypted = point(b"Home", 70, mode="wpa-psk")
        second_adapter = point(b"Home", 60, device="wifi1")
        result = select_access_points([point(b"Home", 90), active, encrypted, second_adapter, point(b"", 100)])
        self.assertEqual(result, [active, encrypted, second_adapter])

    def test_password_validation_uses_bytes_and_distinguishes_sae(self):
        self.assertFalse(valid_password("short", "wpa-psk"))
        self.assertTrue(valid_password("eight123", "wpa-psk"))
        self.assertTrue(valid_password("a" * 64, "wpa-psk"))
        self.assertFalse(valid_password("z" * 64, "wpa-psk"))
        self.assertFalse(valid_password("é" * 32, "wpa-psk"))
        self.assertTrue(valid_password("x", "sae"))
        self.assertFalse(valid_password("", "sae"))


class ConnectivityFixture:
    def setUp(self):
        self.gio = Mock()
        self.gio.Cancellable.return_value.is_cancelled.return_value = False
        self.gio.DBusNodeInfo.new_for_xml.return_value = SimpleNamespace(interfaces=[Mock()])
        self.gio.DBusCallFlags = SimpleNamespace(NONE=0, NO_AUTO_START=1, ALLOW_INTERACTIVE_AUTHORIZATION=2)
        def widget_factory(*args, **kwargs):
            return Mock()
        self.gtk = SimpleNamespace(
            Box=MockBox, Container=MockBox, CssProvider=Mock(), STYLE_PROVIDER_PRIORITY_APPLICATION=600,
            ToggleButton=Mock(side_effect=widget_factory), Revealer=Mock(side_effect=widget_factory),
            RevealerTransitionType=SimpleNamespace(NONE=0), Image=Mock(), Label=Mock(side_effect=widget_factory),
            Expander=Mock(side_effect=widget_factory), Switch=Mock(side_effect=widget_factory),
            ComboBoxText=Mock(side_effect=widget_factory), Button=Mock(side_effect=widget_factory),
            Entry=Mock(side_effect=widget_factory), ScrolledWindow=Mock(side_effect=widget_factory),
            IconSize=SimpleNamespace(MENU=0), Orientation=SimpleNamespace(HORIZONTAL=0, VERTICAL=1),
            PolicyType=SimpleNamespace(NEVER=0, AUTOMATIC=1),
            InputPurpose=SimpleNamespace(PASSWORD=0, FREE_FORM=1))
        self.glib = SimpleNamespace(Error=DBusError, Variant=lambda signature, value: (signature, value),
                                    timeout_add=Mock(return_value=42), timeout_add_seconds=Mock(return_value=43),
                                    source_remove=Mock(), Bytes=SimpleNamespace(new=lambda value: value),
                                    uuid_string_random=lambda: "test-uuid")
        self.gobject = SimpleNamespace(Object=SimpleNamespace(disconnect=Mock()))
        self.nm = Mock()
        self.nm.DeviceType = SimpleNamespace(ETHERNET=1)
        self.nm.DeviceState = SimpleNamespace(ACTIVATED=100, FAILED=120, PREPARE=40)
        self.nm.DeviceStateReason = SimpleNamespace(NO_SECRETS=7, SUPPLICANT_DISCONNECT=8,
                                                   SUPPLICANT_CONFIG_FAILED=9, SUPPLICANT_FAILED=10,
                                                   SUPPLICANT_TIMEOUT=11)
        self.repo = SimpleNamespace(Gio=self.gio, GLib=self.glib, Gtk=self.gtk, Pango=SimpleNamespace(EllipsizeMode=SimpleNamespace(END=3)), GObject=self.gobject, NM=self.nm)
        self.base = load("connectivity", self.repo)
        self.dependencies = {"nwg_panel.modules.connectivity": self.base}

    def network(self):
        module = load("network", self.repo, self.dependencies)
        with patch.dict(sys.modules, {"gi.repository": self.repo}):
            widget = module.Network()
        widget.client = Mock()
        return widget

    def bluetooth(self):
        self.agent_module = load("bluetooth_agent", self.repo)
        module = load("bluetooth", self.repo, {**self.dependencies,
                                              "nwg_panel.modules.bluetooth_agent": self.agent_module})
        widget = module.Bluetooth()
        widget.bus = Mock()
        widget.agent = Mock()
        return widget

class ConnectivityTests(ConnectivityFixture, unittest.TestCase):
    def test_tile_toggle_uses_backend_state_and_respects_busy(self):
        widget = self.base.ConnectivitySection("Wi-Fi", "network-wireless-symbolic")
        widget.set_power = Mock()
        widget.power.get_active.return_value = True
        widget.toggle_power()
        widget.set_power.assert_called_once_with(False)
        widget.set_power.reset_mock()
        widget.busy = True
        widget.toggle_power()
        widget.set_power.assert_not_called()

    def test_opening_one_connection_menu_closes_the_other(self):
        sections = [Mock(), Mock()]
        sections[0].expander.get_expanded.return_value = True
        self.base.ConnectivityGroup.on_expanded(None, sections[0].expander, None, sections)
        sections[1].expander.set_expanded.assert_called_once_with(False)
        sections[0].expander.set_expanded.assert_not_called()

    def test_password_prompt_clears_secret_on_submit_and_cancel(self):
        widget = self.base.ConnectivitySection("Wi-Fi", "network-wireless-symbolic")
        answered = Mock()
        widget.ask("Password", answered, entry=True, secret=True)
        widget.rows.set_sensitive.assert_called_with(False)
        entry = widget.prompt_entry
        entry.set_visibility.assert_called_with(False)
        entry.get_text.return_value = "secret-password"
        widget.answer_prompt(True)
        answered.assert_called_once_with("secret-password")
        entry.set_text.assert_called_with("")
        widget.ask("Password", answered, entry=True, secret=True)
        entry = widget.prompt_entry
        widget.on_unmap()
        answered.assert_called_with(None)
        entry.set_text.assert_called_with("")

    def test_programmatic_power_update_does_not_change_adapter(self):
        widget = self.base.ConnectivitySection("Bluetooth", "bluetooth-symbolic")
        widget.set_power = Mock()
        widget.updating = True
        self.assertFalse(widget.on_power(None, False))
        widget.set_power.assert_not_called()

    def test_disconnecting_targets_only_selected_network_device(self):
        widget = self.network()
        device = Mock()
        widget.disconnect_device(device)
        device.disconnect_async.assert_called_once_with(widget.cancellable, widget.finish, "disconnect_finish")
        widget.client.dbus_set_property.assert_not_called()

    def test_connecting_saved_open_network_does_not_create_duplicate(self):
        widget = self.network()
        device, ap, saved = Mock(), Mock(), Mock()
        widget.client.get_connections.return_value = [saved]
        widget.connect_network(device, dict(active=False, security="open", ap=ap))
        widget.client.activate_connection_async.assert_called_once()
        widget.client.add_and_activate_connection_async.assert_not_called()

    def test_saved_password_missing_prompts_in_panel_instead_of_requiring_tray_agent(self):
        widget = self.network()
        connection, device, ap = Mock(), Mock(), Mock()
        device.get_state.return_value = 30
        connection.get_secrets_finish.return_value = SimpleNamespace(unpack=lambda: {})
        point = dict(security="wpa-psk", ssid=b"Home", ap=ap)
        widget.activate_saved(connection, device, point)
        callback = connection.get_secrets_async.call_args.args[2]
        callback(connection, Mock(), None)
        self.assertIsNotNone(widget.prompt_entry)
        widget.prompt_entry.set_visibility.assert_called_with(False)
        widget.client.activate_connection_async.assert_not_called()

    def test_saved_password_is_reused_without_prompt(self):
        widget = self.network()
        connection, device, ap = Mock(), Mock(), Mock()
        device.get_state.return_value = 30
        connection.get_secrets_finish.return_value = SimpleNamespace(
            unpack=lambda: {"802-11-wireless-security": {"psk": "already-stored"}})
        widget.activate_saved(connection, device, dict(security="wpa-psk", ssid=b"Home", ap=ap))
        connection.get_secrets_async.call_args.args[2](connection, Mock(), None)
        self.assertIsNone(widget.prompt_entry)
        widget.client.activate_connection_async.assert_called_once()

    def test_closed_popup_does_not_reopen_async_password_prompt(self):
        widget = self.network()
        connection, device, ap = Mock(), Mock(), Mock()
        widget.activate_saved(connection, device, dict(security="wpa-psk", ssid=b"Home", ap=ap))
        widget.on_unmap()
        connection.get_secrets_async.call_args.args[2](connection, Mock(), None)
        self.assertIsNone(widget.prompt_entry)
        self.assertFalse(widget.busy)
        widget.client.activate_connection_async.assert_not_called()

    def test_failed_authentication_allows_replacing_saved_password(self):
        widget = self.network()
        connection, device, ap = Mock(), Mock(), Mock()
        device.get_state.return_value = 120
        device.get_state_reason.return_value = 7
        connection.get_secrets_finish.return_value = SimpleNamespace(
            unpack=lambda: {"802-11-wireless-security": {"psk": "old-password"}})
        widget.activate_saved(connection, device, dict(security="wpa-psk", ssid=b"Home", ap=ap))
        connection.get_secrets_async.call_args.args[2](connection, Mock(), None)
        self.assertIsNotNone(widget.prompt_entry)
        widget.client.activate_connection_async.assert_not_called()

    def test_new_password_is_only_added_to_networkmanager_connection(self):
        widget = self.network()
        widget.add_network(Mock(), dict(security="wpa-psk", ssid=b"Home", ap=Mock()), "test-password")
        self.assertEqual(widget.NM.SettingWirelessSecurity.new.return_value.props.psk, "test-password")
        widget.client.add_and_activate_connection_async.assert_called_once()

    def test_invalid_password_does_not_activate_network(self):
        widget = self.network()
        widget.add_network(Mock(), dict(security="wpa-psk", ssid=b"Home", ap=Mock()), "short")
        widget.client.add_and_activate_connection_async.assert_not_called()
        self.assertTrue(widget.message.set_text.called)

    def test_enterprise_setup_is_not_guessed(self):
        widget = self.network()
        widget.client.get_connections.return_value = []
        widget.connect_network(Mock(), dict(active=False, security="enterprise", ap=Mock()))
        widget.client.add_and_activate_connection_async.assert_not_called()
        widget.message.set_text.assert_called_with(
            "Configure this network's authentication in a NetworkManager settings editor first.")

    def test_wifi_failure_reenables_controls_and_shows_error(self):
        widget = self.network()
        widget.on_devices_changed = Mock()
        source = Mock()
        source.request_scan_finish.side_effect = DBusError("Permission denied")
        widget.finish(source, Mock(), "request_scan_finish")
        self.assertFalse(widget.busy)
        widget.message.set_text.assert_called_with("Permission denied")

    def test_scan_session_cleanup_does_not_stop_other_clients(self):
        widget = self.bluetooth()
        widget.discovery_path = "/org/bluez/hci0"
        widget.discovery_timer = 43
        widget.stop_scan()
        self.glib.source_remove.assert_called_once_with(43)
        self.assertIsNone(widget.discovery_path)
        args = widget.bus.call.call_args.args
        self.assertEqual(args[:4], ("org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1", "StopDiscovery"))
        widget.bus.reset_mock()
        widget.stop_scan()
        widget.bus.call.assert_not_called()

    def test_scan_pending_when_popup_closes_is_released(self):
        widget = self.bluetooth()
        widget.scan_request = "/org/bluez/hci0"
        widget.on_unmap()
        widget.bus.call.assert_called_once()
        widget.agent.cancel.assert_called_once_with(widget)
        self.assertIsNone(widget.scan_request)

    def test_two_panels_share_pairing_agent(self):
        agent_module = load("bluetooth_agent", self.repo)
        bus = Mock()
        self.assertIs(agent_module.get_agent(bus), agent_module.get_agent(bus))
        bus.register_object.assert_called_once()

    def test_unavailable_bluetooth_hides_section(self):
        widget = self.bluetooth()
        widget.on_unavailable(DBusError("Service unavailable"))
        widget.hide.assert_called_once()
        self.assertFalse(widget.loading)


class BluetoothAgentTests(ConnectivityFixture, unittest.TestCase):
    def agent(self):
        module = load("bluetooth_agent", self.repo)
        agent = module.BluetoothAgent(Mock())
        agent.sender = ":1.bluez"
        agent.owner = Mock()
        agent.device = "/org/bluez/hci0/dev_00_11"
        return agent

    def request(self, agent, method, arguments, sender=":1.bluez"):
        invocation = Mock()
        agent.on_method(agent.bus, sender, agent.path, "org.bluez.Agent1", method,
                        SimpleNamespace(unpack=lambda: arguments), invocation)
        return invocation

    def test_spoofed_pairing_request_is_rejected(self):
        agent = self.agent()
        invocation = self.request(agent, "RequestAuthorization", (agent.device,), ":1.attacker")
        invocation.return_dbus_error.assert_called_once()
        agent.owner.ask.assert_not_called()

    def test_unsolicited_device_is_rejected(self):
        agent = self.agent()
        invocation = self.request(agent, "RequestAuthorization", ("/other/device",))
        invocation.return_dbus_error.assert_called_once()
        agent.owner.ask.assert_not_called()

    def test_confirmation_requires_explicit_user_answer(self):
        agent = self.agent()
        invocation = self.request(agent, "RequestConfirmation", (agent.device, 42))
        invocation.return_value.assert_not_called()
        self.assertEqual(agent.owner.ask.call_args.args[0], "Does code 000042 match the code on your device?")
        agent.owner.ask.call_args.args[1](True)
        invocation.return_value.assert_called_once_with(None)

    def test_cancel_rejects_pending_prompt_and_cancels_pairing(self):
        agent = self.agent()
        owner = agent.owner
        invocation = self.request(agent, "RequestConfirmation", (agent.device, 123456))
        agent.cancel(owner)
        invocation.return_dbus_error.assert_called_once()
        self.assertIsNone(agent.owner)
        self.assertEqual(owner.call.call_args.args[2], "CancelPairing")

    def test_passkey_validation(self):
        for value, valid in [("000042", True), ("1234567", False), ("-1", False), ("１２", False)]:
            with self.subTest(value=value):
                agent = self.agent()
                invocation = self.request(agent, "RequestPasskey", (agent.device,))
                agent.owner.ask.call_args.args[1](value)
                if valid:
                    invocation.return_value.assert_called_once_with(("(u)", (42,)))
                else:
                    invocation.return_dbus_error.assert_called_once()

    def test_other_panel_cannot_cancel_active_pairing(self):
        agent = self.agent()
        owner = agent.owner
        agent.cancel(Mock())
        self.assertIs(agent.owner, owner)

    def test_pairing_timeout_cancels_daemon_request(self):
        agent = self.agent()
        owner = agent.owner
        agent.on_pair_error(DBusError("Timed out"))
        self.assertIsNone(agent.owner)
        self.assertEqual(owner.call.call_args.args[2], "CancelPairing")
        owner.show_message.assert_called_once_with("Timed out")

    def test_old_pairing_callback_cannot_cancel_a_new_request(self):
        agent = self.agent()
        original = agent.owner
        agent.start_pair()
        failure = original.call.call_args.args[5]
        agent.generation += 1
        new_owner = agent.owner = Mock()
        failure(DBusError("Old request timed out"))
        self.assertIs(agent.owner, new_owner)
        new_owner.cancel_prompt.assert_not_called()

    def test_old_daemon_registration_does_not_survive_restart(self):
        agent = self.agent()
        agent.on_registered((), agent.generation, ":1.old-bluez")
        self.assertFalse(agent.registered)


if __name__ == "__main__":
    unittest.main()

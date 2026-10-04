import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

from nwg_panel.modules.sway_workspace_utils import select_workspaces, workspace_label, workspace_command


def workspace(name, num, output="DP-1", **state):
    return SimpleNamespace(name=name, num=num, output=output,
                           focused=state.get("focused", False),
                           visible=state.get("visible", False), urgent=state.get("urgent", False))


class WorkspaceIdentityTests(unittest.TestCase):
    def test_numeric_order_and_output_filter(self):
        workspaces = [workspace("98:AI", 98), workspace("10:Code", 10),
                      workspace("2:Web", 2), workspace("1:Other", 1, "DP-2")]
        self.assertEqual([ws.name for ws in select_workspaces(workspaces, output="DP-1")],
                         ["2:Web", "10:Code", "98:AI"])

    def test_named_workspaces_remain_distinct(self):
        workspaces = [workspace("chat", -1), workspace("mail", -1), workspace("2:Web", 2)]
        self.assertEqual([ws.name for ws in select_workspaces(workspaces)], ["2:Web", "chat", "mail"])

    def test_number_filter_matches_full_names(self):
        workspaces = [workspace("98:AI", 98), workspace("2:Web", 2)]
        self.assertEqual(select_workspaces(workspaces, [98], "DP-1"), [workspaces[0]])

    def test_placeholders_only_in_all_output_mode(self):
        workspaces = [workspace("2:Web", 2, "DP-2")]
        self.assertEqual(select_workspaces(workspaces, [1, 2], "DP-1"), [])
        self.assertEqual([ws.name for ws in select_workspaces(workspaces, [1, 2])], ["1", "2:Web"])

    def test_label_modes_preserve_identity(self):
        ws = workspace("98:AI", 98)
        self.assertEqual(workspace_label(ws, "name"), "AI")
        self.assertEqual(workspace_label(ws, "number"), "98")
        self.assertEqual(workspace_label(ws, "full-name"), "98:AI")
        self.assertEqual(ws.name, "98:AI")
        self.assertEqual(workspace_label(workspace("chat:work", -1), "name"), "chat:work")
        self.assertEqual(workspace_label(workspace("chat", -1), "number"), "chat")

    def test_command_quotes_full_name(self):
        self.assertEqual(workspace_command('98:AI "dev"\\test;other'),
                         'workspace "98:AI \\"dev\\"\\\\test;other"')


class MockBox:
    """GTK-free container; child widgets record calls through unittest mocks."""
    def __init__(self, **kwargs):
        pass

    def __getattr__(self, name):
        value = Mock()
        setattr(self, name, value)
        return value


def load_module():
    gtk = SimpleNamespace(Box=MockBox, EventBox=Mock(side_effect=Mock), Label=Mock(side_effect=Mock), Image=Mock(side_effect=Mock),
                          Orientation=SimpleNamespace(HORIZONTAL=0, VERTICAL=1))
    gdk = SimpleNamespace(EventMask=SimpleNamespace(SCROLL_MASK=1),
                          ScrollDirection=SimpleNamespace(UP=0, DOWN=1))
    tools = SimpleNamespace(check_key=lambda settings, key, value: settings.setdefault(key, value),
                            load_autotiling=lambda: [], update_image=Mock(),
                            update_image_fallback_desktop=Mock())
    modules = {"gi": Mock(), "gi.repository": SimpleNamespace(Gtk=gtk, Gdk=gdk, GLib=Mock()),
               "i3ipc": SimpleNamespace(Event=SimpleNamespace(WINDOW="window", WORKSPACE="workspace", OUTPUT="output")),
               "nwg_panel.tools": tools}
    spec = importlib.util.spec_from_file_location("tested_sway_workspaces", Path("nwg_panel/modules/sway_workspaces.py"))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class WorkspaceRefreshTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.tree = Mock()
        self.tree.workspaces.return_value = []
        self.tree.find_focused.return_value = None
        self.i3 = Mock()
        self.i3.get_tree.return_value = self.tree
        self.i3.get_workspaces.return_value = [workspace("98:AI", 98, visible=True, focused=True),
                                               workspace("2:Web", 2), workspace("1:Other", 1, "DP-2")]
        self.settings = {"show-icon": False, "show-name": False, "show-layout": False,
                         "mark-content": False, "mark-autotiling": False,
                         "all-outputs": False, "label-format": "name",
                         "disable-scroll-wraparound": True}
        self.widget = self.module.SwayWorkspaces(self.settings, self.i3, "", "DP-1")

    def test_refresh_without_focused_window_and_exact_click(self):
        self.assertEqual(list(self.widget.ws_num2box), ["2:Web", "98:AI"])
        self.widget.ws_num2lbl["98:AI"].set_text.assert_called_with("AI")
        self.widget.on_click(None, None, "98:AI")
        self.i3.command.assert_called_with('workspace "98:AI"')

    def test_rename_move_removal_and_new_numeric_position(self):
        old = self.widget.ws_num2box["98:AI"]
        self.i3.get_workspaces.return_value = [workspace("98:Assistant", 98), workspace("1:Home", 1),
                                               workspace("2:Web", 2, "DP-2")]
        self.widget.refresh()
        old.destroy.assert_called_once()
        self.assertEqual(list(self.widget.ws_num2box), ["1:Home", "98:Assistant"])
        self.widget.num_box.reorder_child.assert_any_call(self.widget.ws_num2box["1:Home"], 0)

    def test_hide_empty_keeps_visible_workspace_on_unfocused_output(self):
        self.settings["hide-empty"] = True
        self.i3.get_workspaces.return_value[0].focused = False
        self.widget.refresh()
        self.assertEqual(list(self.widget.ws_num2box), ["98:AI"])

    def test_occupancy_independent_of_window_details(self):
        tree_ws = Mock(name="tree_workspace")
        tree_ws.name = "2:Web"
        tree_ws.leaves.return_value = [Mock()]
        self.tree.workspaces.return_value = [tree_ws]
        self.settings.update({"hide-empty": True, "mark-content": True})
        self.widget.refresh()
        self.widget.ws_num2lbl["2:Web"].set_text.assert_called_with("Web.")
        self.widget.ws_num2lbl["2:Web"].set_property.assert_called_with("name", "workspace-occupied")

    def test_workspace_name_is_plain_text(self):
        self.i3.get_workspaces.return_value = [workspace("98:<AI & Code>", 98)]
        self.widget.refresh()
        label = self.widget.ws_num2lbl["98:<AI & Code>"]
        label.set_text.assert_called_with("<AI & Code>")
        label.set_markup.assert_not_called()

    def test_scroll_stops_at_end_and_stays_on_output(self):
        event = SimpleNamespace(direction=self.module.Gdk.ScrollDirection.DOWN)
        self.widget.on_scroll(None, event)
        self.i3.command.assert_not_called()
        event.direction = self.module.Gdk.ScrollDirection.UP
        self.widget.on_scroll(None, event)
        self.i3.command.assert_called_once_with('workspace "2:Web"')

    def test_optional_scroll_wraparound(self):
        self.settings["disable-scroll-wraparound"] = False
        self.widget.on_scroll(None, SimpleNamespace(direction=self.module.Gdk.ScrollDirection.DOWN))
        self.i3.command.assert_called_once_with('workspace "2:Web"')

    def test_legacy_integer_numbers_and_custom_markup(self):
        self.settings.update({"numbers": [98], "custom-labels": ["<b>Assistant</b>"]})
        widget = self.module.SwayWorkspaces(self.settings, self.i3, "", "DP-1")
        widget.ws_num2lbl["98:AI"].set_markup.assert_called_with("<b>Assistant</b>")

    def test_legacy_defaults_keep_all_outputs_numbers_and_placeholders(self):
        settings = {"numbers": [1, 2, 3, 98], "show-icon": False,
                    "show-name": False, "show-layout": False,
                    "mark-content": False, "mark-autotiling": False}
        widget = self.module.SwayWorkspaces(settings, self.i3, "", "DP-1")
        self.assertEqual([ws.name for ws in widget.displayed_workspaces],
                         ["1:Other", "2:Web", "3", "98:AI"])
        widget.ws_num2lbl["98:AI"].set_text.assert_called_with("98")
        self.assertTrue(settings["all-outputs"])
        self.assertFalse(settings["disable-scroll-wraparound"])

    def test_focus_visibility_and_urgency_classes_are_removed(self):
        ws = self.i3.get_workspaces.return_value[0]
        ws.urgent = True
        self.widget.refresh()
        context = self.widget.ws_num2box[ws.name].get_style_context.return_value
        for state in ("focused", "visible", "urgent"):
            context.add_class.assert_any_call(state)
        ws.focused = ws.visible = ws.urgent = False
        self.widget.refresh()
        for state in ("focused", "visible", "urgent"):
            context.remove_class.assert_any_call(state)

    def test_occupancy_style_clears_when_last_window_closes(self):
        ws = SimpleNamespace(name="2:Web", leaves=lambda: [object()])
        self.tree.workspaces.return_value = [ws]
        self.settings["mark-content"] = True
        self.widget.refresh()
        label = self.widget.ws_num2lbl[ws.name]
        label.set_text.assert_called_with("Web.")
        self.tree.workspaces.return_value = []
        self.widget.refresh()
        label.set_text.assert_called_with("Web")
        label.set_property.assert_called_with("name", "")

    def test_empty_list_and_unsupported_scroll_do_not_issue_commands(self):
        self.i3.get_workspaces.return_value = []
        self.widget.refresh()
        self.assertTrue(self.widget.on_scroll(None, SimpleNamespace(direction=0)))
        self.assertFalse(self.widget.on_scroll(None, SimpleNamespace(direction=99)))
        self.i3.command.assert_not_called()

    def test_focused_window_details_and_output_filter(self):
        focused = SimpleNamespace(type="con", name="A long title", app_id="editor",
                                  window_class=None, floating="auto_off",
                                  parent=SimpleNamespace(layout="tabbed"),
                                  workspace=lambda: SimpleNamespace(name="98:AI"))
        self.tree.find_focused.return_value = focused
        self.settings.update({"show-name": True, "show-icon": True,
                              "show-layout": True, "name-length": 6})
        self.widget.refresh()
        self.widget.name_label.set_text.assert_called_with("A long")
        self.module.update_image_fallback_desktop.assert_called_once()
        self.module.update_image.assert_called_with(self.widget.layout_icon, "view-dual-symbolic", 16, "")
        focused.workspace = lambda: SimpleNamespace(name="1:Other")
        self.widget.refresh()
        self.widget.name_label.set_text.assert_called_with("")
        self.widget.icon.hide.assert_called_once()
        self.widget.layout_icon.hide.assert_called_once()

    def test_floating_window_details_use_window_class_fallback(self):
        self.tree.find_focused.return_value = SimpleNamespace(
            type="con", name="Floating", app_id=None, window_class="XTerm",
            floating="user_on", workspace=lambda: SimpleNamespace(name="98:AI"))
        self.assertEqual(self.widget.find_details(self.tree, {"98:AI"}),
                         ("Floating", "XTerm", "floating"))


class WorkspaceConfigTests(unittest.TestCase):
    def test_editor_and_runtime_legacy_defaults_agree(self):
        tree = ast.parse(Path("nwg_panel/config.py").read_text())
        editor = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "EditorWrapper")
        method = next(node for node in editor.body if isinstance(node, ast.FunctionDef) and node.name == "edit_sway_workspaces")
        assignment = next(node for node in method.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == "defaults" for target in node.targets))
        defaults = ast.literal_eval(assignment.value)
        self.assertTrue(defaults["all-outputs"])
        self.assertEqual(defaults["label-format"], "number")
        self.assertFalse(defaults["disable-scroll-wraparound"])

    def test_save_automatic_and_explicit_workspace_lists(self):
        # Exercise the editor's save method without starting its GTK application.
        tree = ast.parse(Path("nwg_panel/config.py").read_text())
        editor = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "EditorWrapper")
        method = next(node for node in editor.body if isinstance(node, ast.FunctionDef) and node.name == "update_sway_workspaces")
        namespace = {"save_json": Mock()}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "config.py", "exec"), namespace)
        for automatic, text, expected in ((True, "1 2 3", []), (False, "", []), (False, "2 98", ["2", "98"])):
            with self.subTest(automatic=automatic, text=text):
                instance = Mock()
                instance.panel = {"sway-workspaces": {"numbers": ["1", "2", "3"]}}
                instance.eb_workspaces_menu.get_text.return_value = text
                instance.ws_dynamic.get_active.return_value = automatic
                instance.ws_all_outputs.get_active.return_value = False
                instance.ws_label_format.get_active_id.return_value = "name"
                instance.ws_no_wrap.get_active.return_value = True
                for attr in ("ws_custom_labels", "ws_focused_labels"):
                    buffer = getattr(instance, attr).get_buffer.return_value
                    buffer.get_bounds.return_value = (0, 0)
                    buffer.get_text.return_value = ""
                for attr in ("ws_show_icon", "ws_show_name", "ws_mark_autotiling", "ws_mark_content", "ws_hide_empty", "ws_show_layout"):
                    getattr(instance, attr).get_active.return_value = False
                instance.ws_image_size.get_value.return_value = 16
                instance.ws_name_length.get_value.return_value = 40
                instance.ws_angle.get_active_id.return_value = "0.0"
                namespace["update_sway_workspaces"](instance)
                settings = instance.panel["sway-workspaces"]
                self.assertEqual(settings["numbers"], expected)
                self.assertEqual(settings["label-format"], "name")
                self.assertFalse(settings["all-outputs"])
                self.assertTrue(settings["disable-scroll-wraparound"])

if __name__ == "__main__":
    unittest.main()

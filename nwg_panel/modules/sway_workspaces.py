#!/usr/bin/env python3

from gi.repository import Gtk, Gdk, GLib
from i3ipc import Event

from nwg_panel.tools import check_key, update_image, update_image_fallback_desktop, load_autotiling

from nwg_panel.modules.sway_workspace_utils import select_workspaces, workspace_label, workspace_command


class SwayWorkspaces(Gtk.Box):
    def __init__(self, settings, i3, icons_path, display_name=None):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.settings = settings
        self.i3 = i3
        self.display_name = display_name
        self.displayed_workspaces = []
        self.num_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.num_box.set_property("name", "sway-workspaces")
        self.ws_num2box = {}
        self.ws_num2lbl = {}
        self.name_label = Gtk.Label()
        self.name_label.set_property("name", "sway-workspaces-name")
        self.win_id = ""
        self.win_pid = None
        self.icon = Gtk.Image()
        self.icon.set_property("name", "sway-workspaces-icon")
        self.layout_icon = Gtk.Image()
        self.icons_path = icons_path
        self.autotiling = load_autotiling()
        self.build_box()
        self.refresh()
        self.subscribe()

    def subscribe(self):
        self.i3.on(Event.WINDOW, self.on_i3ipc_event)
        self.i3.on(Event.WORKSPACE, self.on_i3ipc_event)
        self.i3.on(Event.OUTPUT, self.on_i3ipc_event)

    def build_box(self):
        check_key(self.settings, "numbers", [])
        self.settings["numbers"] = [str(num) for num in self.settings["numbers"]]
        # Missing options belong to older configurations. New panels explicitly
        # opt into per-output lists and name labels in the configuration skeleton.
        check_key(self.settings, "all-outputs", True)
        check_key(self.settings, "label-format", "number")
        check_key(self.settings, "disable-scroll-wraparound", False)
        check_key(self.settings, "custom-labels", [])
        check_key(self.settings, "focused-labels", [])
        check_key(self.settings, "show-icon", True)
        check_key(self.settings, "image-size", 16)
        check_key(self.settings, "show-name", True)
        check_key(self.settings, "name-length", 40)
        check_key(self.settings, "mark-autotiling", True)
        check_key(self.settings, "mark-content", True)
        check_key(self.settings, "hide-empty", False)
        check_key(self.settings, "show-layout", True)
        check_key(self.settings, "angle", 0.0)
        if self.settings["angle"] != 0.0:
            self.set_orientation(Gtk.Orientation.VERTICAL)
            self.num_box.set_orientation(Gtk.Orientation.VERTICAL)

        if len(self.settings["custom-labels"]) == 1:
            self.settings["custom-labels"] *= len(self.settings["numbers"])
        elif len(self.settings["custom-labels"]) != len(self.settings["numbers"]):
            self.settings["custom-labels"] = []

        if len(self.settings["focused-labels"]) == 1:
            self.settings["focused-labels"] *= len(self.settings["numbers"])
        elif len(self.settings["focused-labels"]) != len(self.settings["numbers"]):
            self.settings["focused-labels"] = []

        self.pack_start(self.num_box, False, False, 0)

        if self.settings["show-icon"]:
            self.pack_start(self.icon, False, False, 6)

        if self.settings["show-name"]:
            self.pack_start(self.name_label, False, False, 0)

        if self.settings["show-layout"]:
            self.pack_start(self.layout_icon, False, False, 6)

    def build_number(self, num, label):
        eb = Gtk.EventBox()
        eb.connect("enter_notify_event", self.on_enter_notify_event)
        eb.connect("leave_notify_event", self.on_leave_notify_event)
        eb.connect("button-release-event", self.on_click, num)
        eb.add_events(Gdk.EventMask.SCROLL_MASK)
        eb.connect('scroll-event', self.on_scroll)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.set_property("name", "sway-workspaces-item")
        if self.settings["angle"] != 0.0:
            box.set_orientation(Gtk.Orientation.VERTICAL)
        eb.add(box)

        lbl = Gtk.Label(label=label)
        if self.settings["angle"] != 0.0:
            lbl.set_angle(self.settings["angle"])
            self.name_label.set_angle(self.settings["angle"])

        self.ws_num2box[num] = eb
        self.ws_num2lbl[num] = lbl

        box.pack_start(lbl, False, False, 6)

        return eb, lbl

    def on_i3ipc_event(self, i3conn, event):
        GLib.idle_add(self.refresh, priority=GLib.PRIORITY_HIGH)

    def refresh(self):
        tree = self.i3.get_tree()
        output = None if self.settings["all-outputs"] else self.display_name
        workspaces = select_workspaces(self.i3.get_workspaces(), self.settings["numbers"], output)
        non_empty = {ws.name for ws in tree.workspaces() if ws.leaves()}
        self.displayed_workspaces = [ws for ws in workspaces
                                     if not self.settings["hide-empty"] or ws.name in non_empty
                                     or ws.visible or ws.focused]
        names = {ws.name for ws in self.displayed_workspaces}
        for name in list(self.ws_num2box):
            if name not in names:
                self.ws_num2box.pop(name).destroy()
                del self.ws_num2lbl[name]

        for position, ws in enumerate(self.displayed_workspaces):
            text = workspace_label(ws, self.settings["label-format"])
            custom = False
            number = str(ws.num)
            if number in self.settings["numbers"]:
                idx = self.settings["numbers"].index(number)
                labels = (self.settings["focused-labels"]
                          if ws.focused and self.settings["focused-labels"]
                          else self.settings["custom-labels"])
                if labels:
                    text = labels[idx]
                    custom = True
            if self.settings["mark-autotiling"] and ws.num in self.autotiling:
                text = "a" + text
            if self.settings["mark-content"] and ws.name in non_empty and not text.endswith("."):
                text += "."
            if ws.name not in self.ws_num2box:
                eb, lbl = self.build_number(ws.name, text)
                self.num_box.pack_start(eb, False, False, 0)
                eb.show_all()
            eb, lbl = self.ws_num2box[ws.name], self.ws_num2lbl[ws.name]
            self.num_box.reorder_child(eb, position)
            eb.set_tooltip_text(ws.name)
            eb.set_property("name", "task-box-focused" if ws.focused else "task-box")
            context = eb.get_style_context()
            for state in ("focused", "visible", "urgent"):
                if getattr(ws, state, False):
                    context.add_class(state)
                else:
                    context.remove_class(state)
            lbl.set_property("name", "workspace-occupied" if ws.name in non_empty else "")
            if custom:
                lbl.set_markup(text)
            else:
                lbl.set_text(text)

        win_name, win_id, win_layout = self.find_details(tree, names)
        if self.settings["show-icon"] and win_id != self.win_id:
            self.update_icon(win_id, win_name)
            self.win_id = win_id
        if self.settings["show-name"]:
            self.name_label.set_text(win_name)

        if self.settings["show-layout"]:
            if win_name:
                if win_layout == "splith":
                    update_image(self.layout_icon, "go-next-symbolic", self.settings["image-size"], self.icons_path)
                elif win_layout == "splitv":
                    update_image(self.layout_icon, "go-down-symbolic", self.settings["image-size"], self.icons_path)
                elif win_layout == "tabbed":
                    update_image(self.layout_icon, "view-dual-symbolic", self.settings["image-size"],
                                 self.icons_path)
                elif win_layout == "stacked":
                    update_image(self.layout_icon, "view-paged-symbolic", self.settings["image-size"],
                                 self.icons_path)
                else:
                    update_image(self.layout_icon, "window-pop-out-symbolic", self.settings["image-size"],
                                 self.icons_path)

                if not self.layout_icon.get_visible():
                    self.layout_icon.show()
            else:
                if self.layout_icon.get_visible():
                    self.layout_icon.hide()

    def update_icon(self, win_id, win_name):
        loaded_icon = False
        if win_id and win_name:
            try:
                update_image_fallback_desktop(self.icon,
                                              win_id,
                                              self.settings["image-size"],
                                              self.icons_path,
                                              fallback=False)
                loaded_icon = True
                if not self.icon.get_visible():
                    self.icon.show()
            except:
                pass

        if not loaded_icon and self.icon.get_visible():
            self.icon.hide()

    def find_details(self, tree, names):
        focused = tree.find_focused()
        if not focused or focused.type != "con" or not focused.name:
            return "", "", None
        ws = focused.workspace()
        if not ws or ws.name not in names:
            return "", "", None
        layout = "floating" if focused.floating in ("user_on", "auto_on") else focused.parent.layout
        return (focused.name[:self.settings["name-length"]],
                focused.app_id or focused.window_class or "", layout)

    def on_click(self, event_box, event_button, name):
        self.i3.command(workspace_command(name))

    def on_scroll(self, event_box, event):
        if event.direction not in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN):
            return False
        workspaces = self.displayed_workspaces
        current = next((idx for idx, ws in enumerate(workspaces) if ws.focused), None)
        if current is None:
            current = next((idx for idx, ws in enumerate(workspaces) if ws.visible), None)
        if current is None:
            return True
        target = current + (-1 if event.direction == Gdk.ScrollDirection.UP else 1)
        if self.settings["disable-scroll-wraparound"]:
            target = max(0, min(target, len(workspaces) - 1))
        else:
            target %= len(workspaces)
        if target != current:
            self.i3.command(workspace_command(workspaces[target].name))
        return True

    def on_enter_notify_event(self, widget, event):
        widget.set_state_flags(Gtk.StateFlags.DROP_ACTIVE, clear=False)
        widget.set_state_flags(Gtk.StateFlags.SELECTED, clear=False)

    def on_leave_notify_event(self, widget, event):
        widget.unset_state_flags(Gtk.StateFlags.DROP_ACTIVE)
        widget.unset_state_flags(Gtk.StateFlags.SELECTED)

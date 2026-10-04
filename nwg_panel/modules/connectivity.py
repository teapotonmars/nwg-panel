"""Shared GTK presentation for asynchronous connectivity controls."""

from gi.repository import Gio, GLib, GObject, Gtk, Pango


class ConnectivitySection(Gtk.Box):
    def __init__(self, title, icon):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_no_show_all(True)
        self.cancellable = Gio.Cancellable()
        self.handlers = []
        self.refresh_source = 0
        self.updating = False
        self.busy = False
        self.prompt_callback = None
        self.prompt_entry = None
        self.interaction_generation = 0
        self.title = title

        self.header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.header.get_style_context().add_class("connectivity-tile")
        self.toggle = Gtk.Button()
        self.toggle.get_style_context().add_class("connectivity-toggle")
        self.toggle.set_tooltip_text("Enable or disable " + title)
        self.toggle.connect("clicked", self.toggle_power)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
        self.label = Gtk.Label(label=title)
        self.label.set_max_width_chars(16)
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        self.label.set_xalign(0)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        heading = Gtk.Label(label=title, xalign=0)
        heading.get_style_context().add_class("connectivity-heading")
        self.label.get_style_context().add_class("connectivity-subtitle")
        labels.pack_start(heading, False, False, 0)
        labels.pack_start(self.label, False, False, 0)
        header.pack_start(labels, True, True, 0)
        self.toggle.add(header)
        self.header.pack_start(self.toggle, True, True, 0)
        self.menu_button = Gtk.ToggleButton()
        self.menu_button.set_image(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.MENU))
        self.menu_button.set_tooltip_text("Choose " + title + " connections")
        self.menu_button.get_style_context().add_class("connectivity-menu-button")
        self.header.pack_end(self.menu_button, False, False, 0)
        self.pack_start(self.header, False, False, 0)
        self.expander = Gtk.Expander()
        # Keep expansion state independent of the tile's power button.
        self.menu_button.connect("toggled", lambda button: self.expander.set_expanded(button.get_active()))
        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.NONE)
        self.expander.connect("notify::expanded", self.reveal_details)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.get_style_context().add_class("connectivity-details")
        self.revealer.add(content)
        self.pack_start(self.revealer, False, False, 0)

        self.toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.power = Gtk.Switch()
        self.power.set_tooltip_text("Enable " + title)
        self.power.connect("state-set", self.on_power)
        self.power.connect("notify::active", self.update_tile)
        self.power.connect("notify::sensitive", self.update_tile)
        self.adapter = Gtk.ComboBoxText()
        self.adapter.set_no_show_all(True)
        self.toolbar.pack_start(self.adapter, True, True, 0)
        self.scan_button = Gtk.Button(label="Scan")
        self.scan_button.connect("clicked", self.scan)
        self.toolbar.pack_end(self.scan_button, False, False, 0)
        content.pack_start(self.toolbar, False, False, 0)

        self.message = Gtk.Label(xalign=0)
        self.message.set_line_wrap(True)
        self.message.set_max_width_chars(40)
        self.message.set_no_show_all(True)
        content.pack_start(self.message, False, False, 0)
        self.prompt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.prompt.set_no_show_all(True)
        content.pack_start(self.prompt, False, False, 0)
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(240)
        scroll.set_propagate_natural_height(True)
        scroll.add(self.rows)
        content.pack_start(scroll, False, False, 0)
        self.header.show_all()
        self.revealer.show_all()
        provider = Gtk.CssProvider()
        provider.load_from_data(TILE_CSS.encode())
        apply_style(self, provider)
        self.expander.connect("notify::expanded", self.on_collapse)
        self.connect("destroy", self.on_destroy)
        self.connect("unmap", self.on_unmap)

    def toggle_power(self, *args):
        self.on_power(self.power, not self.power.get_active())

    def update_tile(self, *args):
        context = self.header.get_style_context()
        if self.power.get_active():
            context.add_class("enabled")
        else:
            context.remove_class("enabled")
        self.toggle.set_sensitive(self.power.get_sensitive() and not self.busy and self.prompt_callback is None)

    def reveal_details(self, *args):
        expanded = self.expander.get_expanded()
        self.revealer.set_reveal_child(expanded)
        if self.menu_button.get_active() != expanded:
            self.menu_button.set_active(expanded)

    def watch(self, obj, signal, callback=None):
        handler = obj.connect(signal, callback or self.schedule_refresh)
        self.handlers.append((obj, handler))

    def schedule_refresh(self, *args):
        if not self.refresh_source and not self.cancellable.is_cancelled():
            self.refresh_source = GLib.timeout_add(250, self.refresh)

    def refresh(self):
        self.refresh_source = 0
        if not self.cancellable.is_cancelled():
            self.sync()
        return False

    def clear_rows(self):
        for child in self.rows.get_children():
            child.destroy()

    def add_row(self, text, action=None, callback=None, sensitive=True):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label = Gtk.Label(label=text, xalign=0)
        label.set_max_width_chars(30)
        label.set_ellipsize(3)
        label.set_tooltip_text(text)
        row.pack_start(label, True, True, 0)
        if action:
            button = Gtk.Button(label=action)
            button.set_sensitive(sensitive)
            button.connect("clicked", lambda *args: callback())
            row.pack_end(button, False, False, 0)
        self.rows.pack_start(row, False, False, 0)

    def show_message(self, text):
        self.message.set_text(text)
        self.message.set_visible(bool(text))

    def set_busy(self, busy):
        self.busy = busy
        enabled = not busy and self.prompt_callback is None
        self.toolbar.set_sensitive(enabled)
        self.rows.set_sensitive(enabled)
        self.update_tile()

    def ask(self, text, callback, entry=False, secret=False):
        self.cancel_prompt()
        for child in self.prompt.get_children():
            child.destroy()
        label = Gtk.Label(label=text, xalign=0)
        label.set_line_wrap(True)
        label.set_max_width_chars(40)
        self.prompt.pack_start(label, False, False, 0)
        self.prompt_callback = callback
        self.update_tile()
        self.toolbar.set_sensitive(False)
        self.rows.set_sensitive(False)
        self.prompt_entry = None
        if entry:
            self.prompt_entry = Gtk.Entry()
            self.prompt_entry.set_visibility(not secret)
            self.prompt_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD if secret else Gtk.InputPurpose.FREE_FORM)
            self.prompt_entry.connect("activate", lambda *args: self.answer_prompt(True))
            self.prompt.pack_start(self.prompt_entry, False, False, 0)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for text, accepted in (("Cancel", False), ("Confirm", True)):
            button = Gtk.Button(label=text)
            button.connect("clicked", lambda button, accepted: self.answer_prompt(accepted), accepted)
            buttons.pack_end(button, False, False, 0)
        self.prompt.pack_start(buttons, False, False, 0)
        self.prompt.show_all()
        self.prompt.show()
        self.expander.set_expanded(True)
        if self.prompt_entry:
            self.prompt_entry.grab_focus()

    def answer_prompt(self, accepted):
        callback, self.prompt_callback = self.prompt_callback, None
        value = self.prompt_entry.get_text() if accepted and self.prompt_entry else accepted
        if self.prompt_entry:
            self.prompt_entry.set_text("")
        self.prompt_entry = None
        self.prompt.hide()
        self.update_tile()
        self.toolbar.set_sensitive(not self.busy)
        self.rows.set_sensitive(not self.busy)
        if callback:
            callback(value if accepted else None)

    def cancel_prompt(self):
        self.answer_prompt(False)

    def on_power(self, switch, enabled):
        if self.updating:
            return False
        if not self.busy:
            self.set_power(enabled)
        return True

    def on_unmap(self, *args):
        self.interaction_generation += 1
        self.cancel_prompt()

    def on_collapse(self, *args):
        if not self.expander.get_expanded():
            self.interaction_generation += 1
            self.cancel_prompt()

    def on_destroy(self, *args):
        self.cancel_prompt()
        self.cancellable.cancel()
        if self.refresh_source:
            GLib.source_remove(self.refresh_source)
            self.refresh_source = 0
        for obj, handler in self.handlers:
            GObject.Object.disconnect(obj, handler)
        self.handlers = []


TILE_CSS = """
.connectivity-tile { border-radius: 24px; background-color: alpha(@theme_fg_color, 0.10); }
.connectivity-tile button { background-image: none; background-color: transparent;
    border: none; box-shadow: none; padding: 12px; }
.connectivity-tile .connectivity-toggle { border-radius: 24px 0 0 24px; }
.connectivity-tile .connectivity-menu-button { border-radius: 0 24px 24px 0;
    border-left: 1px solid alpha(@theme_fg_color, 0.12); padding: 10px; }
.connectivity-tile.enabled { background-color: @theme_selected_bg_color; color: @theme_selected_fg_color; }
.connectivity-tile.enabled label, .connectivity-tile.enabled image { color: @theme_selected_fg_color; }
.connectivity-tile button:hover { background-color: alpha(@theme_fg_color, 0.10); }
.connectivity-heading { font-weight: bold; }
.connectivity-subtitle { font-size: 0.85em; }
.connectivity-details { border-radius: 16px; padding: 12px;
    background-color: alpha(@theme_fg_color, 0.06); }
"""


def apply_style(widget, provider):
    widget.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            apply_style(child, provider)


class ConnectivityGroup(Gtk.Box):
    """Two quick toggles with mutually exclusive full-width connection menus."""
    def __init__(self, sections):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        tiles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, homogeneous=True)
        self.pack_start(tiles, False, False, 0)
        for section in sections:
            section.header.set_no_show_all(True)
            section.remove(section.header)
            tiles.pack_start(section.header, True, True, 0)
            self.pack_start(section, False, False, 0)
            section.connect("notify::visible", lambda widget, prop: widget.header.set_visible(widget.get_visible()))
            section.header.set_visible(section.get_visible())
            section.expander.connect("notify::expanded", self.on_expanded, sections)

    def on_expanded(self, selected, property, sections):
        if selected.get_expanded():
            for section in sections:
                if section.expander is not selected:
                    section.expander.set_expanded(False)

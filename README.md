<img src="https://github.com/nwg-piotr/nwg-panel/assets/20579136/36327f89-05b8-420d-998a-8f5f7d385545" width="90" style="margin-right:10px" align=left alt="nwg-shell logo">
<H1>nwg-panel</H1><br>

This application is a part of the [nwg-shell](https://nwg-piotr.github.io/nwg-shell) project.

**Nwg-panel** is a GTK3-based panel for [sway](https://github.com/swaywm/sway) and [Hyprland](https://github.com/hyprwm/Hyprland) 
Wayland compositors. The panel is equipped with a graphical configuration program that frees the user from the need to 
manually edit configuration files.

Sway workspace lists can follow each panel's output and update automatically as workspaces are
created, renamed, moved or removed. In the graphical configuration, open **Sway workspaces**,
select **Show all existing workspaces**, and leave **All outputs** disabled. Choose **Name without
number** to display `98:AI` as `AI`, **Full workspace name** to display `98:AI`, or **Workspace
number** to display `98`. Buttons retain the full workspace identity and sort by workspace number;
the tooltip shows the full name. Custom/focused labels still override labels for configured numbers.
An empty workspace-number list enables automatic discovery. New configurations use automatic,
per-output lists and name-only labels; existing number lists remain filters until automatic discovery
is selected. Configurations without the new options retain all-output lists, numeric labels and
scroll wraparound. Empty placeholders from a configured number list are available in all-output mode;
per-output mode shows only existing workspaces assigned to that output.
Scrolling follows the displayed workspace list and can stop at either end. Turn off content and
autotiling markers if you want only the workspace name on each button.

Enable **Power Mode** in the controls settings to add a power profile selector to the
controls popup. It offers the profiles supported by `power-profiles-daemon` (Performance,
Balanced and Power Saver), shows the active mode and follows changes made by other apps.
The selector is hidden when the daemon is unavailable. This component can also be enabled
by adding `"power-profiles"` to `"controls-settings"` → `"components"`.

**Network / Wi-Fi** and **Bluetooth** are optional controls components (`"network"`
and `"bluetooth"`). Enable them in the controls editor to manage connections inside
the popup without NetworkManager or Bluetooth tray applets.

Network controls require NetworkManager and its `NM-1.0` GObject introspection
bindings (provided by `libnm` on Arch Linux). They offer a Wi-Fi switch, adapter
selection, scanning, signal strength, saved connections, open/WPA/WPA2/WPA3-Personal
connections, encrypted password entry and disconnect controls. Ethernet connection
status and disconnect are also available. Passwords are stored by NetworkManager,
not in the panel configuration. Existing enterprise/WEP profiles can be activated;
creating those profiles requires a NetworkManager settings editor. Enterprise
profiles that need interactive credentials still require a NetworkManager secret
agent. Hidden networks must likewise be configured beforehand.

Bluetooth controls require BlueZ. They offer adapter selection, power, scanning,
pairing with PIN/passkey/confirmation prompts, and device connect/disconnect.
Successful pairing trusts the device for future connections. Discovery stops after
30 seconds or when the popup closes. The panel registers its own pairing agent
without replacing another application's default agent. Closing a pairing prompt
cancels the request; unsolicited pairing requests are rejected.

Both components update through asynchronous D-Bus notifications, hide when their
service or hardware is unavailable, and display failed operations in the popup.

<img src="https://github.com/nwg-piotr/nwg-panel/assets/20579136/09866188-6819-4dfb-99df-40af53be859b" width=640><br>

<img src="https://github.com/nwg-piotr/nwg-panel/assets/20579136/1aeb8990-f355-4ba9-80e3-9aa2a46730ca" width=640><br>

Currently, we have a dozen of modules, and we don't plan on many more. Many minor tasks that users request a module for,
may be easily done with [executors](https://github.com/nwg-piotr/nwg-panel/wiki/modules:-Executor).

- **Controls module**: basis system controls like brightness slider, volume slider (w/ per-app sliders), battery 
level w/ low level notification, system processes viewer, user-defined custom items, user-defined drop-down menu 
(which is the power menu by default);
- **Brightness slider**: a separate brightness slider for use per monitor; features backlight via ddcutil;
- **Clock**: system clock w/ a calendar popup built in;
- **Custom button**: a user-defined graphical/textual button you could bind an action to. By default, we use one as the 
application launcher button;
- **DWL tags**: deprecated and no longer supported; will be deleted in the future;
- **Executor**: a useful module that executes user-provided code and displays the output in the panel as an icon and 
text; see Wiki for more info;
- **Sway taskbar & Hyprland taskbar & Niri taskbar**: highly customizable modules to display a label with an icon for every running 
window, together with some more info (workspace number, split orientation on sway, X-widows marker); right click opens 
a menu that allows to move windows between workspaces, toggle floating and fullscreen, and also close windows;
- **Sway & Hyprland workspaces**: display labels to navigate between workspaces with a marker for non-empty ones; next
to the labels there's a field with currently focused window details;
- **Menu Start**: module provides integration of the XGD-style [nwg-menu](https://github.com/nwg-piotr/nwg-menu);
- **Openweather**: displays weather forcast from OpenWeatherMap and weather alerts from weatherbit.io for given locations;
- **Playerctl**: displays an icon and a label of the currently played tune, together with back / play-pause / forward 
buttons;
- **RandomWallpaper**: provides you with random wallpapers from either a local folder, or the [wallhaven.cc](wallhaven.cc) service. You can refresh them on startup, on demand or in a given time interval. 
You can also see the remote image info, and save the image to a local folder of your choice.
- **Scratchpad**: displays info on current scratchpad content and allows to open scratchpad windows; 
- **SwayMode**: a simple indicator of a sway bindings mode other than "default";
- **HyprlandSubmap**: a simple indicator of a Hyprland bindings submap other than "default";
- **Tray**: SNI system tray module;
- **KeyboardLayout**: keyboard layout switcher, between values defined as `xkb_layout` (sway) or `kb_layout` (Hyprland).
Use commas to separate values, e.g. `pl,us,de`;
- **Pinned**: displays buttons corresponding to pinned items from nwg-drawer/nwg-menu

## Installation

[![Packaging status](https://repology.org/badge/vertical-allrepos/nwg-panel.svg)](https://repology.org/project/nwg-panel/versions)

If nwg-panel has not yet been packaged for your Linux distribution, you may install it by cloning this repository
and running the `install.sh` script.

## Known issues:

If `kded6` is running (e.g., started by launching Dolphin), it may register `org.kde.StatusNotifierWatcher` and 
prevent nwg-panel from owning the system tray. You can stop it using:

```
pkill kded6
```

See: https://github.com/nwg-piotr/nwg-panel/issues/396

See [Wiki](https://github.com/nwg-piotr/nwg-panel/wiki) for more information. You'll also find some useful executor examples there.

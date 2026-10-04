"""Workspace identity, ordering and labels, independent of GTK."""
import re
from types import SimpleNamespace


def select_workspaces(workspaces, numbers=(), output=None):
    numbers = [str(number) for number in numbers]
    selected = [ws for ws in workspaces
                if (not output or ws.output == output)
                and (not numbers or str(ws.num) in numbers)]
    # Unassigned placeholders only make sense when showing all outputs.
    if numbers and not output:
        present = {str(ws.num) for ws in workspaces}
        selected += [SimpleNamespace(name=num, num=int(num), focused=False,
                                     visible=False, urgent=False, output=None)
                     for num in numbers if num not in present]
    return sorted(selected, key=lambda ws: (ws.num < 0, ws.num if ws.num >= 0 else 0, ws.name))


def workspace_label(workspace, mode):
    if mode == "number":
        return str(workspace.num) if workspace.num >= 0 else workspace.name
    if mode == "name":
        return re.sub(r"^\d+:", "", workspace.name)
    return workspace.name


def workspace_command(name):
    # Sway's quoted command arguments require escaping quotes and backslashes.
    return 'workspace "{}"'.format(name.replace('\\', '\\\\').replace('"', '\\"'))

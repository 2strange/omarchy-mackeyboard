#!/usr/bin/env python3
"""keyboard-config: the Mac keyboard layout switch and the special keys of the function row.

Writes ~/.config/hypr/mackeyboard.lua from a JSON state line at its top. The plugin's
hypr/bindings.lua loads that file (or its built-in defaults while there is none). Every write
reloads Hyprland and checks `hyprctl configerrors`; on a new error the previous file is put back
and the exit code is 1. The Fn switch itself (hid_apple fnmode) is not here: see Service.qml.

  keyboard-config get                      # settings, the Mac's special keys and actions, as JSON
  keyboard-config set mac_layout=true      # right Option works as on a Mac (your layout's mac variant)
  keyboard-config set key.XF86LaunchA=apps # what a special key does (see ACTIONS)
  keyboard-config set-command XF86LaunchA 'omarchy-shell -q macos.dock altTabNext'
  keyboard-config cheatsheet               # Option characters of your layout's mac variant, as JSON
  keyboard-config reset                    # remove mackeyboard.lua (the loader block stays)

On the first write the loader block of scripts/setup is appended to ~/.config/hypr/bindings.lua
when it is not there yet, so the layout switch works without the Fn setup (which needs sudo).
"""
import ctypes
import json
import os
import re
import subprocess
import sys
import tempfile

PLUGIN_ID = "io.github.2strange.mackeyboard"
HOME = os.path.expanduser("~")
TARGET = os.path.join(HOME, ".config/hypr/mackeyboard.lua")
BINDINGS = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "hypr/bindings.lua")
MARK_BEGIN = f"-- >>> {PLUGIN_ID} >>>"
MARK_END = f"-- <<< {PLUGIN_ID} <<<"
LOADER = f"""
{MARK_BEGIN}
-- Mac Keyboard plugin: function-row bindings and the Mac layout switch.
-- Managed by the plugin's setup/uninstall scripts; edit the plugin copy instead.
local mac_keyboard = os.getenv("HOME") .. "/.config/omarchy/plugins/{PLUGIN_ID}/hypr/bindings.lua"
local mac_keyboard_file = io.open(mac_keyboard)
if mac_keyboard_file then
  mac_keyboard_file:close()
  dofile(mac_keyboard)
end
{MARK_END}
"""
STATE_PREFIX = "-- state: "
XKB_SYMBOLS = "/usr/share/X11/xkb/symbols"

# The keys that differ between Mac generations (the rest of the row is the same everywhere:
# brightness, media, volume). fn: printed position; on: which Macs send it.
KEYS = [
    {"keysym": "XF86LaunchA", "fn": "F3", "label": "Mission Control", "on": ["intel", "apple-silicon"], "default": "apps"},
    {"keysym": "XF86LaunchB", "fn": "F4", "label": "Launchpad", "on": ["intel"], "default": "menu"},
    {"keysym": "XF86Search", "fn": "F4", "label": "Spotlight", "on": ["apple-silicon"], "default": "menu"},
    {"keysym": "XF86KbdBrightnessDown", "fn": "F5", "label": "Keyboard light down", "on": ["intel"], "default": "kbd_down"},
    {"keysym": "XF86Dictate", "fn": "F5", "label": "Dictation", "on": ["apple-silicon"], "default": "dictation"},
    {"keysym": "XF86KbdBrightnessUp", "fn": "F6", "label": "Keyboard light up", "on": ["intel"], "default": "kbd_up"},
    {"keysym": "XF86Sleep", "fn": "F6", "label": "Do Not Disturb", "on": ["apple-silicon"], "default": "dnd"},
]
KEYSYMS = {k["keysym"]: k for k in KEYS}
# Keys Omarchy itself binds: a different action has to unbind Omarchy's first.
OMARCHY_BOUND = {"XF86KbdBrightnessDown", "XF86KbdBrightnessUp"}

# value -> (label, lua that binds it; {key} is the keysym as a Lua string)
ACTIONS = {
    "none": ("Nothing", None),
    "menu": ("Omarchy menu", 'o.bind({key}, "Omarchy menu", "omarchy-menu toggle", {{ locked = true }})'),
    "apps": ("Apps menu", 'o.bind({key}, "Apps menu", "omarchy-menu toggle apps", {{ locked = true }})'),
    "dnd": ("Do Not Disturb", 'o.bind_toggle({key}, "Do Not Disturb", "notification-silencing", {{ locked = true }})'),
    "kbd_down": ("Keyboard light down", 'o.bind({key}, "Keyboard brightness down", "omarchy-brightness-keyboard down", {{ locked = true, repeating = true }})'),
    "kbd_up": ("Keyboard light up", 'o.bind({key}, "Keyboard brightness up", "omarchy-brightness-keyboard up", {{ locked = true, repeating = true }})'),
    "screenshot": ("Screenshot", 'o.bind({key}, "Screenshot", "omarchy-capture-screenshot")'),
    "capture": ("Capture menu", 'o.bind({key}, "Capture menu", "omarchy-menu toggle capture")'),
    "dictation": ("Dictation (voxtype)", 'if o.cmd_present("voxtype") then o.bind({key}, "Toggle dictation", "voxtype record toggle") end'),
    "command": ("Own command", None),  # set-command: the command is stored per key
}


def hyprctl(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=5).stdout


def live_str(option):
    try:
        return str(json.loads(hyprctl("getoption", "-j", option)).get("str", ""))
    except (ValueError, subprocess.SubprocessError, AttributeError):
        return ""


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def put(path, text):
    """Atomic write; None removes the file."""
    path = os.path.realpath(path)  # write through a symlink (dotfile managers) instead of replacing it
    if text is None:
        if os.path.exists(path):
            os.remove(path)
        return
    try:
        mode = os.stat(path).st_mode & 0o7777
    except FileNotFoundError:
        mode = 0o644
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".mackeyboard.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def lua_string(text):
    out = []
    for ch in text:
        if ch in ('"', "\\"):
            out.append("\\" + ch)
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append("\\%03d" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def saved():
    text = read(TARGET) or ""
    first = text.split("\n", 1)[0]
    if first.startswith(STATE_PREFIX):
        try:
            state = json.loads(first[len(STATE_PREFIX):])
            if isinstance(state, dict):
                return state
        except ValueError:
            pass
    return {}


# ---------------------------------------------------------------- the Mac and its layouts

def family():
    """intel, apple-silicon or unknown, from the firmware's own model name."""
    try:
        with open("/proc/device-tree/model", "rb") as f:  # Apple Silicon (Asahi): "Apple MacBook Pro (14-inch, M3 ...)"
            if f.read().startswith(b"Apple "):
                return "apple-silicon"
    except OSError:
        pass
    vendor = read("/sys/class/dmi/id/sys_vendor") or ""
    product = read("/sys/class/dmi/id/product_name") or ""
    if vendor.strip().startswith("Apple") and product.strip().startswith("Mac"):
        return "intel"
    return "unknown"


def model():
    for path in ("/proc/device-tree/model", "/sys/class/dmi/id/product_name"):
        text = (read(path) or "").replace("\0", "").strip()
        if text:
            return text
    return ""


def has_mac_variant(layout):
    """True if the xkb symbols file of this layout has a "mac" variant."""
    if not re.fullmatch(r"[a-z]{2,8}", layout or ""):
        return False
    text = read(os.path.join(XKB_SYMBOLS, layout)) or ""
    return re.search(r'xkb_symbols\s+"mac"', text) is not None


def layouts():
    return [part.strip() for part in live_str("input:kb_layout").split(",")]


def mac_variant(lays, own):
    """kb_variant with "mac" for every layout that has one; the others keep their own variant."""
    own_parts = own.split(",") if own else []
    out = []
    for i, lay in enumerate(lays):
        mine = own_parts[i].strip() if i < len(own_parts) else ""
        out.append("mac" if has_mac_variant(lay) else mine)
    return ",".join(out)


# ---------------------------------------------------------------- state -> lua

def effective():
    state = saved()
    keys = state.get("keys") if isinstance(state.get("keys"), dict) else {}
    commands = state.get("commands") if isinstance(state.get("commands"), dict) else {}
    out_keys = {}
    for k in KEYS:
        action = keys.get(k["keysym"], k["default"])
        if action not in ACTIONS or (action == "command" and not commands.get(k["keysym"])):
            action = k["default"]
        out_keys[k["keysym"]] = action
    return {
        "mac_layout": state.get("mac_layout") if isinstance(state.get("mac_layout"), bool) else None,
        "own_variant": str(state.get("own_variant", "")),
        "keys": out_keys,
        "commands": {k: str(v) for k, v in commands.items() if k in KEYSYMS and isinstance(v, str) and v.strip()},
    }


def render(s, lays):
    state = {"mac_layout": s["mac_layout"], "own_variant": s["own_variant"],
             "keys": s["keys"], "commands": s["commands"]}
    lines = [STATE_PREFIX + json.dumps(state, sort_keys=True),
             f"-- Generated by the Mac Keyboard bar plugin ({PLUGIN_ID}). Edit through its menu, not by hand.", ""]
    if s["mac_layout"] is True:
        lines.append(f"hl.config({{ input = {{ kb_variant = {lua_string(mac_variant(lays, s['own_variant']))} }} }})")
    elif s["mac_layout"] is False:
        lines.append(f"hl.config({{ input = {{ kb_variant = {lua_string(s['own_variant'])} }} }})")
    lines.append("")
    for k in KEYS:
        sym = k["keysym"]
        action = s["keys"][sym]
        if sym in OMARCHY_BOUND and action != k["default"]:
            lines.append(f"hl.unbind({lua_string(sym)})")
        if sym in OMARCHY_BOUND and action == k["default"]:
            continue  # Omarchy's own binding stays
        if action == "command":
            cmd = s["commands"][sym]
            lines.append(f'o.bind({lua_string(sym)}, {lua_string(k["label"] + ": own command")}, {lua_string(cmd)})')
            continue
        tmpl = ACTIONS[action][1]
        if tmpl:
            lines.append(tmpl.format(key=lua_string(sym)))
    return "\n".join(lines) + "\n"


def apply(changes):
    """Write {path: text}, reload Hyprland, and put every file back if it reports errors."""
    old = {path: read(path) for path in changes}
    try:
        before = hyprctl("configerrors").strip()
        for path, text in changes.items():
            put(path, text)
        hyprctl("reload")
        errors = hyprctl("configerrors").strip()
    except Exception as err:  # hyprctl missing or timing out: never leave a half-applied change
        errors, before = f"keyboard-config: {err}", None
    if errors and errors != before:
        for path, text in old.items():
            put(path, text)
        try:
            hyprctl("reload")
        except Exception:
            pass
        print(errors, file=sys.stderr)
        return 1
    return 0


def write(state):
    changes = {TARGET: render(state, layouts())}
    current = read(BINDINGS) or ""
    if MARK_BEGIN not in current:
        changes[BINDINGS] = current.rstrip("\n") + "\n" + LOADER
    return apply(changes)


# ---------------------------------------------------------------- cheat sheet (libxkbcommon)

class _RuleNames(ctypes.Structure):
    _fields_ = [(n, ctypes.c_char_p) for n in ("rules", "model", "layout", "variant", "options")]


# Physical rows of an ISO Mac keyboard, xkb key names.
ROWS = [
    ["TLDE", "AE01", "AE02", "AE03", "AE04", "AE05", "AE06", "AE07", "AE08", "AE09", "AE10", "AE11", "AE12"],
    ["AD01", "AD02", "AD03", "AD04", "AD05", "AD06", "AD07", "AD08", "AD09", "AD10", "AD11", "AD12"],
    ["AC01", "AC02", "AC03", "AC04", "AC05", "AC06", "AC07", "AC08", "AC09", "AC10", "AC11", "BKSL"],
    ["LSGT", "AB01", "AB02", "AB03", "AB04", "AB05", "AB06", "AB07", "AB08", "AB09", "AB10"],
]


def cheatsheet(layout, variant):
    """[[{key, base, shift, option, shift_option}, ...] per row] for layout(variant)."""
    xkb = ctypes.CDLL("libxkbcommon.so.0")
    xkb.xkb_context_new.restype = ctypes.c_void_p
    xkb.xkb_keymap_new_from_names.restype = ctypes.c_void_p
    xkb.xkb_keymap_new_from_names.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RuleNames), ctypes.c_int]
    xkb.xkb_keymap_key_by_name.restype = ctypes.c_uint32
    xkb.xkb_keymap_key_by_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    xkb.xkb_keymap_key_get_syms_by_level.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                                     ctypes.c_uint32, ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32))]
    xkb.xkb_keysym_to_utf32.restype = ctypes.c_uint32
    xkb.xkb_keysym_to_utf32.argtypes = [ctypes.c_uint32]
    xkb.xkb_keysym_get_name.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t]
    xkb.xkb_keymap_unref.argtypes = [ctypes.c_void_p]
    xkb.xkb_context_unref.argtypes = [ctypes.c_void_p]
    ctx = xkb.xkb_context_new(0)
    names = _RuleNames(b"evdev", b"pc105", layout.encode(), variant.encode(), b"")
    keymap = xkb.xkb_keymap_new_from_names(ctx, ctypes.byref(names), 0)
    if not keymap:
        xkb.xkb_context_unref(ctx)
        raise ValueError(f"no keymap for {layout}({variant})")

    def char(code, level):
        syms = ctypes.POINTER(ctypes.c_uint32)()
        if xkb.xkb_keymap_key_get_syms_by_level(keymap, code, 0, level, ctypes.byref(syms)) < 1:
            return ""
        sym = syms[0]
        cp = xkb.xkb_keysym_to_utf32(sym)
        if cp:
            return chr(cp)
        buf = ctypes.create_string_buffer(64)
        xkb.xkb_keysym_get_name(sym, buf, 64)
        name = buf.value.decode()
        if name.startswith("dead_"):  # a dead key: shown as its accent, marked
            base = {"tilde": "~", "circumflex": "^", "grave": "`", "acute": "´", "diaeresis": "¨"}.get(name[5:])
            return (base + "̲") if base else ""
        return ""

    rows = []
    for row in ROWS:
        out = []
        for key in row:
            code = xkb.xkb_keymap_key_by_name(keymap, key.encode())
            if not code:
                continue
            out.append({"key": key, "base": char(code, 0), "shift": char(code, 1),
                        "option": char(code, 2), "shift_option": char(code, 3)})
        rows.append(out)
    xkb.xkb_keymap_unref(keymap)
    xkb.xkb_context_unref(ctx)
    return rows


# ---------------------------------------------------------------- cli

def info():
    s = effective()
    lays = layouts()
    fam = family()
    variant = live_str("input:kb_variant")
    available = any(has_mac_variant(lay) for lay in lays)
    mac_now = s["mac_layout"] if s["mac_layout"] is not None else ("mac" in variant.split(","))
    return {
        "mac_layout": mac_now,
        "mac_available": available,
        "layout": ",".join(lays),
        "variant": variant,
        "family": fam,
        "model": model(),
        "keys": [dict(k, action=s["keys"][k["keysym"]], command=s["commands"].get(k["keysym"], ""),
                      mine=(fam == "unknown" or fam in k["on"])) for k in KEYS],
        "actions": [{"value": v, "label": label} for v, (label, _) in ACTIONS.items()],
    }


def parse_bool(raw):
    if raw.lower() in ("1", "true", "yes", "on"):
        return True
    if raw.lower() in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"not a boolean: {raw}")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd == "get":
        print(json.dumps(info()))
        return 0
    if cmd == "cheatsheet":
        lays = layouts()
        lay = next((x for x in lays if has_mac_variant(x)), lays[0] if lays else "us")
        variant = "mac" if has_mac_variant(lay) else ""
        print(json.dumps({"layout": lay, "variant": variant, "rows": cheatsheet(lay, variant)}, ensure_ascii=False))
        return 0
    if cmd == "reset":
        return apply({TARGET: None})
    s = effective()
    if cmd == "set":
        for arg in args:
            key, sep, raw = arg.partition("=")
            if not sep:
                print(f"keyboard-config: expected key=value, got {arg}", file=sys.stderr)
                return 2
            try:
                if key == "mac_layout":
                    on = parse_bool(raw)
                    if on and not any(has_mac_variant(lay) for lay in layouts()):
                        print("keyboard-config: your keyboard layout has no Mac variant", file=sys.stderr)
                        return 2
                    if on and s["mac_layout"] is not True:
                        own = live_str("input:kb_variant")  # remember the variant to go back to
                        s["own_variant"] = ",".join("" if part.strip() == "mac" else part for part in own.split(",")) if own else ""
                    s["mac_layout"] = on
                elif key.startswith("key.") and key[4:] in KEYSYMS:
                    if raw not in ACTIONS or raw == "command":
                        raise ValueError(f"unknown action {raw} (own commands: set-command)")
                    s["keys"][key[4:]] = raw
                else:
                    raise ValueError(f"unknown setting {key}")
            except ValueError as err:
                print(f"keyboard-config: {err}", file=sys.stderr)
                return 2
        return write(s)
    if cmd == "set-command":
        if len(args) != 2 or args[0] not in KEYSYMS:
            print("keyboard-config: set-command <keysym> <command>", file=sys.stderr)
            return 2
        command = args[1].strip()
        if not command or "\n" in command:
            print("keyboard-config: the command must be one non-empty line", file=sys.stderr)
            return 2
        s["commands"][args[0]] = command
        s["keys"][args[0]] = "command"
        return write(s)
    print(f"keyboard-config: unknown command {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

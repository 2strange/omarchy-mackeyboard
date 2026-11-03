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
  keyboard-config refresh                  # rewrite after kb_layout changed
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
CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")  # the hypr/bindings.lua loaders use the same
TARGET = os.path.join(CONFIG, "hypr/mackeyboard.lua")
BINDINGS = os.path.join(CONFIG, "hypr/bindings.lua")
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
# Loader blocks of the plugins this one replaces: with one of them still in bindings.lua the special
# keys would be bound twice (and e.g. a menu would open and close at once), so writing stops.
FOREIGN_MARKS = {
    "-- >>> io.github.2strange.mac-fnkeys >>>": "Mac Fn keys",
    "-- >>> io.github.alnandr.macbook-fn-keys >>>": "MacBook Function Keys",
}
EXIT_FOREIGN = 4
STATE_PREFIX = "-- state: "
XKB_SYMBOLS = "/usr/share/X11/xkb/symbols"

# The keys that differ between Mac generations (the rest of the row is the same everywhere:
# brightness, media, volume). fn: printed position; on: which Macs send it.
KEYS = [
    {"keysym": "XF86LaunchA", "fn": "F3", "label": "Mission Control", "on": ["intel", "apple-silicon"], "default": "apps"},
    {"keysym": "XF86LaunchB", "fn": "F4", "label": "Launchpad", "on": ["intel"], "default": "menu"},
    {"keysym": "XF86Search", "fn": "F4", "label": "Spotlight", "on": ["apple-silicon"], "default": "menu"},
    {"keysym": "XF86KbdBrightnessDown", "fn": "F5", "label": "Keyboard light down", "on": ["intel"], "default": "kbd_down"},
    # Measured upstream on a MacBookPro18,3 (M1 Pro): Dictation sends KEY_MICMUTE.
    {"keysym": "XF86AudioMicMute", "fn": "F5", "label": "Dictation", "on": ["apple-silicon"], "default": "mic_mute"},
    {"keysym": "XF86KbdBrightnessUp", "fn": "F6", "label": "Keyboard light up", "on": ["intel"], "default": "kbd_up"},
    {"keysym": "XF86Sleep", "fn": "F6", "label": "Do Not Disturb", "on": ["apple-silicon"], "default": "dnd"},
]
KEYSYMS = {k["keysym"]: k for k in KEYS}
# Keys Omarchy itself binds: a different action has to unbind Omarchy's first.
OMARCHY_BOUND = {"XF86KbdBrightnessDown", "XF86KbdBrightnessUp", "XF86AudioMicMute"}

# value -> (label, lua that binds it; {key} is the keysym as a Lua string)
ACTIONS = {
    "none": ("Nothing", None),
    "menu": ("Omarchy menu", 'o.bind({key}, "Omarchy menu", "omarchy-menu toggle", {{ locked = true }})'),
    "apps": ("Apps menu", 'o.bind({key}, "Apps menu", "omarchy-menu toggle apps", {{ locked = true }})'),
    "dnd": ("Do Not Disturb", 'o.bind_toggle({key}, "Do Not Disturb", "notification-silencing", {{ locked = true }})'),
    "kbd_down": ("Keyboard light down", 'o.bind({key}, "Keyboard brightness down", "omarchy-brightness-keyboard down", {{ locked = true, repeating = true }})'),
    "kbd_up": ("Keyboard light up", 'o.bind({key}, "Keyboard brightness up", "omarchy-brightness-keyboard up", {{ locked = true, repeating = true }})'),
    "mic_mute": ("Microphone mute", 'o.bind({key}, "Mute microphone", "omarchy-audio-input-mute", {{ locked = true }})'),
    "screenshot": ("Screenshot", 'o.bind({key}, "Screenshot", "omarchy-capture-screenshot")'),
    "capture": ("Capture menu", 'o.bind({key}, "Capture menu", "omarchy-menu toggle capture")'),
    "dictation": ("Dictation (voxtype)", 'if o.cmd_present("voxtype") then o.bind({key}, "Toggle dictation", "voxtype record toggle") end'),
    "command": ("Own command", None),  # set-command: the command is stored per key
}


def hyprctl(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=5).stdout


def hyprctl_checked(*args):
    """stdout of a hyprctl call that must work; raises when it fails (missing, IPC down, error)."""
    r = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        raise RuntimeError(f"hyprctl {' '.join(args)} failed: {(r.stderr or r.stdout).strip() or r.returncode}")
    return r.stdout


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
    if text is None:
        if os.path.lexists(path):
            os.remove(path)  # a symlink is removed, never the file it points to
        return
    path = os.path.realpath(path)  # write through a symlink (dotfile managers) instead of replacing it
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


def own_variants_now(lays):
    """{layout: variant} as configured now, without "mac" (that is what the switch adds)."""
    parts = [part.strip() for part in live_str("input:kb_variant").split(",")]
    out = {}
    for i, lay in enumerate(lays):
        mine = parts[i] if i < len(parts) else ""
        out[lay] = "" if mine == "mac" else mine
    return out


def variant_for(lays, own, mac):
    """kb_variant for these layouts: "mac" where the layout has one (if mac), else the own variant."""
    return ",".join("mac" if mac and has_mac_variant(lay) else own.get(lay, "") for lay in lays)


def active_layout(lays):
    """The layout the main keyboard uses right now (first one if Hyprland does not say)."""
    try:
        boards = json.loads(hyprctl("devices", "-j")).get("keyboards", [])
        main = next((b for b in boards if b.get("main")), boards[0] if boards else {})
        idx = int(main.get("active_layout_index", 0))
    except (ValueError, TypeError, subprocess.SubprocessError, AttributeError, IndexError):
        idx = 0
    return lays[idx] if 0 <= idx < len(lays) else (lays[0] if lays else "us")


# ---------------------------------------------------------------- state -> lua

def good_command(v):
    return isinstance(v, str) and v.strip() != "" and "\n" not in v and "\r" not in v


def effective():
    """The saved state, every field checked: anything odd falls back to the default."""
    state = saved()
    keys = state.get("keys") if isinstance(state.get("keys"), dict) else {}
    commands = state.get("commands") if isinstance(state.get("commands"), dict) else {}
    commands = {k: v.strip() for k, v in commands.items() if k in KEYSYMS and good_command(v)}
    own = state.get("own_variants") if isinstance(state.get("own_variants"), dict) else {}
    own = {k: v for k, v in own.items()
           if isinstance(k, str) and re.fullmatch(r"[a-z]{2,8}", k) and isinstance(v, str) and re.fullmatch(r"[a-z0-9_]*", v)}
    out_keys = {}
    for k in KEYS:
        action = keys.get(k["keysym"], k["default"])
        if not isinstance(action, str) or action not in ACTIONS or (action == "command" and k["keysym"] not in commands):
            action = k["default"]
        out_keys[k["keysym"]] = action
    mac = state.get("mac_layout")
    written = state.get("written_for")
    return {
        "mac_layout": mac if isinstance(mac, bool) else None,
        "own_variants": own,
        "written_for": written if isinstance(written, list) and all(isinstance(x, str) for x in written) else [],
        "keys": out_keys,
        "commands": commands,
    }


def render(s, lays):
    state = {"mac_layout": s["mac_layout"], "own_variants": s["own_variants"], "written_for": lays,
             "keys": s["keys"], "commands": s["commands"]}
    lines = [STATE_PREFIX + json.dumps(state, sort_keys=True),
             f"-- Generated by the Mac Keyboard bar plugin ({PLUGIN_ID}). Edit through its menu, not by hand.", ""]
    if s["mac_layout"] is not None:
        # written for these layouts (kb_layout = "{','.join(lays)}"); the menu rewrites it when they change
        lines.append(f"hl.config({{ input = {{ kb_variant = {lua_string(variant_for(lays, s['own_variants'], s['mac_layout']))} }} }})")
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
    before = None
    try:
        before = hyprctl_checked("configerrors").strip()
        for path, text in changes.items():
            put(path, text)
        hyprctl_checked("reload")
        errors = hyprctl_checked("configerrors").strip()
    except Exception as err:  # hyprctl missing, IPC down or timing out: never leave a half-applied change
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


def foreign_loader(text=None):
    """Name of a replaced plugin whose loader block is still in bindings.lua, or ""."""
    text = read(BINDINGS) if text is None else text
    return next((name for mark, name in FOREIGN_MARKS.items() if mark in (text or "")), "")


def write(state):
    current = read(BINDINGS) or ""
    other = foreign_loader(current)
    if other:
        print(f"keyboard-config: the {other} plugin's block is still in {BINDINGS}: remove that marked block "
              f"first (not with its uninstall script, that removes the Fn helper this plugin uses too)", file=sys.stderr)
        return EXIT_FOREIGN
    changes = {TARGET: render(state, layouts())}
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

# The characters people coming from a Mac look for first, in the order the menu shows them.
EXAMPLE_CHARS = "@|\\{}[]~"
KEY_LABEL = {"AB06": "N", "AC09": "L"}  # fallback labels; normally the key's own base character


def examples(layout):
    """[{char, keys}] for EXAMPLE_CHARS on this layout's Mac variant, e.g. {"@": "⌥L"}; [] if unknown."""
    if not has_mac_variant(layout):
        return []
    try:
        rows = cheatsheet(layout, "mac")
    except (OSError, ValueError):
        return []
    found = {}
    for row in rows:
        for k in row:
            label = (k["base"].replace("\u0332", "") or KEY_LABEL.get(k["key"], k["key"])).upper()
            for level, prefix in (("option", "⌥"), ("shift_option", "⌥⇧")):
                ch = k[level].replace("\u0332", "")
                if ch in EXAMPLE_CHARS and ch not in found:
                    found[ch] = prefix + label
    return [{"char": ch, "keys": found[ch]} for ch in EXAMPLE_CHARS if ch in found]


def info():
    s = effective()
    lays = layouts()
    fam = family()
    variant = live_str("input:kb_variant")
    available = any(has_mac_variant(lay) for lay in lays)
    mac_now = s["mac_layout"] if s["mac_layout"] is not None else ("mac" in variant.split(","))
    active = active_layout(lays)
    return {
        "mac_layout": mac_now,
        "mac_available": available,
        "layout": ",".join(lays),
        "active_layout": active,
        "variant": variant,
        # kb_layout changed since the menu last wrote kb_variant: the menu rewrites it
        "stale": s["mac_layout"] is not None and s["written_for"] != lays,
        "foreign_loader": foreign_loader(),
        "examples": examples(active) if mac_now else [],
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
        lay = active_layout(lays)  # the layout you type with right now
        variant = "mac" if has_mac_variant(lay) else ""
        print(json.dumps({"layout": lay, "variant": variant, "rows": cheatsheet(lay, variant)}, ensure_ascii=False))
        return 0
    if cmd == "reset":
        return apply({TARGET: None})
    s = effective()
    lays = layouts()
    if s["mac_layout"] is None or any(lay not in s["own_variants"] for lay in lays):
        # first touch, or a layout the plugin has not seen: remember the variants it has now
        now = own_variants_now(lays)
        s["own_variants"] = dict(now, **s["own_variants"]) if s["mac_layout"] is not None else now
    if cmd == "refresh":  # rewrite for the current kb_layout
        return write(s)
    if cmd == "set":
        for arg in args:
            key, sep, raw = arg.partition("=")
            if not sep:
                print(f"keyboard-config: expected key=value, got {arg}", file=sys.stderr)
                return 2
            try:
                if key == "mac_layout":
                    on = parse_bool(raw)
                    if on and not any(has_mac_variant(lay) for lay in lays):
                        print("keyboard-config: your keyboard layout has no Mac variant", file=sys.stderr)
                        return 2
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

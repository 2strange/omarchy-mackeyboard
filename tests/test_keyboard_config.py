"""keyboard-config.py with Hyprland and the config files stubbed: nothing on the real system changes."""
import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("keyboard_config", HERE.parent / "keyboard-config.py")
kc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kc)


class FakeHypr:
    """hyprctl getoption/reload/configerrors; errors appear after reload when `fail` is set."""
    def __init__(self, layout="de", variant=""):
        self.options = {"input:kb_layout": layout, "input:kb_variant": variant}
        self.fail = False
        self.reloaded = 0
        self.errors = ""

    def __call__(self, *args):
        if args[:2] == ("getoption", "-j"):
            return json.dumps({"str": self.options[args[2]], "set": True})
        if args == ("reload",):
            self.reloaded += 1
            self.errors = "error: bad config" if self.fail else ""
            return "ok"
        if args == ("configerrors",):
            return self.errors
        return ""


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        symbols = self.dir / "symbols"
        symbols.mkdir()
        (symbols / "de").write_text('xkb_symbols "basic" {};\nxkb_symbols "mac" {};\n')
        (symbols / "fi").write_text('xkb_symbols "basic" {};\n')
        self.bindings = self.dir / "bindings.lua"
        self.bindings.write_text("-- user bindings\n")
        self.hypr = FakeHypr()
        for name, value in (("TARGET", str(self.dir / "mackeyboard.lua")), ("BINDINGS", str(self.bindings)),
                            ("XKB_SYMBOLS", str(symbols)), ("hyprctl", self.hypr)):
            patcher = mock.patch.object(kc, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def generated(self):
        """The generated Lua without its state line (which names every key)."""
        return (self.dir / "mackeyboard.lua").read_text().split("\n", 1)[1]


class Layout(Case):
    def test_mac_variant_only_where_the_layout_has_one(self):
        self.assertEqual(kc.mac_variant(["de"], ""), "mac")
        self.assertEqual(kc.mac_variant(["fi", "de"], "nodeadkeys,"), "nodeadkeys,mac")
        self.assertFalse(kc.has_mac_variant("../etc/passwd"))

    def test_switch_on_then_off_restores_the_own_variant(self):
        self.hypr.options["input:kb_variant"] = "nodeadkeys"
        self.assertEqual(kc.main(["set", "mac_layout=true"]), 0)
        self.assertIn('kb_variant = "mac"', self.generated())
        self.assertEqual(kc.main(["set", "mac_layout=false"]), 0)
        self.assertIn('kb_variant = "nodeadkeys"', self.generated())

    def test_no_mac_variant_is_refused(self):
        self.hypr.options["input:kb_layout"] = "fi"
        self.assertEqual(kc.main(["set", "mac_layout=true"]), 2)
        self.assertFalse((self.dir / "mackeyboard.lua").exists())

    def test_untouched_layout_is_left_to_the_user(self):
        self.assertEqual(kc.main(["set", "key.XF86LaunchA=menu"]), 0)
        self.assertNotIn("kb_variant", self.generated())


class Keys(Case):
    def test_defaults_keep_omarchys_keyboard_light(self):
        kc.main(["set", "key.XF86LaunchA=apps"])
        text = self.generated()
        self.assertIn('o.bind("XF86LaunchA", "Apps menu"', text)
        self.assertNotIn("hl.unbind", text)
        self.assertNotIn("XF86KbdBrightnessUp", text)

    def test_other_action_on_an_omarchy_key_unbinds_it_first(self):
        kc.main(["set", "key.XF86KbdBrightnessUp=screenshot"])
        text = self.generated()
        self.assertLess(text.index('hl.unbind("XF86KbdBrightnessUp")'), text.index('o.bind("XF86KbdBrightnessUp", "Screenshot"'))

    def test_nothing_binds_nothing(self):
        kc.main(["set", "key.XF86LaunchB=none"])
        self.assertNotIn('o.bind("XF86LaunchB"', self.generated())

    def test_own_command_is_escaped(self):
        self.assertEqual(kc.main(["set-command", "XF86LaunchA", 'notify-send "hi" \\o/']), 0)
        self.assertIn('o.bind("XF86LaunchA", "Mission Control: own command", "notify-send \\"hi\\" \\\\o/")', self.generated())
        self.assertEqual(kc.main(["set-command", "XF86LaunchA", "a\nb"]), 2)

    def test_unknown_key_or_action_is_refused(self):
        self.assertEqual(kc.main(["set", "key.XF86Nope=menu"]), 2)
        self.assertEqual(kc.main(["set", "key.XF86LaunchA=rm"]), 2)
        self.assertEqual(kc.main(["set", "key.XF86LaunchA=command"]), 2)

    def test_tampered_state_falls_back_to_defaults(self):
        (self.dir / "mackeyboard.lua").write_text('-- state: {"keys": {"XF86LaunchA": "evil"}, "mac_layout": "yes"}\n')
        s = kc.effective()
        self.assertEqual(s["keys"]["XF86LaunchA"], "apps")
        self.assertIsNone(s["mac_layout"])


class Apply(Case):
    def test_first_write_adds_the_loader_once(self):
        kc.main(["set", "key.XF86LaunchA=menu"])
        kc.main(["set", "key.XF86LaunchA=apps"])
        self.assertEqual(self.bindings.read_text().count(kc.MARK_BEGIN), 1)

    def test_hyprland_error_puts_everything_back(self):
        self.hypr.fail = True
        self.assertEqual(kc.main(["set", "key.XF86LaunchA=menu"]), 1)
        self.assertFalse((self.dir / "mackeyboard.lua").exists())
        self.assertEqual(self.bindings.read_text(), "-- user bindings\n")

    def test_reset_removes_the_settings(self):
        kc.main(["set", "mac_layout=true"])
        self.assertEqual(kc.main(["reset"]), 0)
        self.assertFalse((self.dir / "mackeyboard.lua").exists())


class Cheatsheet(unittest.TestCase):
    def test_german_mac_option_layer(self):
        try:
            rows = kc.cheatsheet("de", "mac")
        except OSError as err:
            self.skipTest(f"no libxkbcommon: {err}")
        keys = {k["base"]: k for row in rows for k in row}
        self.assertEqual(keys["l"]["option"], "@")
        self.assertEqual(keys["7"]["option"], "|")
        self.assertEqual(keys["7"]["shift_option"], "\\")
        self.assertEqual(keys["8"]["option"], "{")


if __name__ == "__main__":
    unittest.main()

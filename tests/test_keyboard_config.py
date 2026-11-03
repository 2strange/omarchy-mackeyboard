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
    """hyprctl getoption/reload/configerrors; errors appear after reload when `fail` is set,
    and every checked call fails when `down` is set (IPC gone)."""
    def __init__(self, layout="de", variant=""):
        self.options = {"input:kb_layout": layout, "input:kb_variant": variant}
        self.fail = False
        self.down = False
        self.reloaded = 0
        self.errors = ""

    def checked(self, *args):
        if self.down:
            raise RuntimeError("hyprctl reload failed: Couldn't connect")
        return self(*args)

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
                            ("XKB_SYMBOLS", str(symbols)), ("hyprctl", self.hypr),
                            ("hyprctl_checked", self.hypr.checked)):
            patcher = mock.patch.object(kc, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def generated(self):
        """The generated Lua without its state line (which names every key)."""
        return (self.dir / "mackeyboard.lua").read_text().split("\n", 1)[1]


class Layout(Case):
    def test_mac_variant_only_where_the_layout_has_one(self):
        self.assertEqual(kc.variant_for(["de"], {}, True), "mac")
        self.assertEqual(kc.variant_for(["fi", "de"], {"fi#0": "nodeadkeys"}, True), "nodeadkeys,mac")
        self.assertEqual(kc.variant_for(["fi", "de"], {"fi#0": "nodeadkeys", "de#0": "nodeadkeys"}, False), "nodeadkeys,nodeadkeys")

    def test_the_same_layout_twice_keeps_both_variants(self):
        self.hypr.options.update({"input:kb_layout": "us,us", "input:kb_variant": "intl,dvorak"})
        self.assertEqual(kc.main(["set", "mac_layout=false"]), 0)
        self.assertIn('kb_variant = "intl,dvorak"', self.generated())
        self.assertFalse(kc.has_mac_variant("../etc/passwd"))

    def test_first_touch_off_keeps_the_other_variants(self):
        self.hypr.options.update({"input:kb_layout": "fi,de", "input:kb_variant": "nodeadkeys,mac"})
        self.assertEqual(kc.main(["set", "mac_layout=false"]), 0)
        self.assertIn('kb_variant = "nodeadkeys,"', self.generated())

    def test_changed_layouts_are_stale_and_refresh_rewrites(self):
        kc.main(["set", "mac_layout=true"])
        self.hypr.options["input:kb_layout"] = "fi,de"
        self.assertTrue(kc.info()["stale"])
        self.assertEqual(kc.main(["refresh"]), 0)
        self.assertIn('kb_variant = ",mac"', self.generated())
        self.assertFalse(kc.info()["stale"])

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
        (self.dir / "mackeyboard.lua").write_text('-- state: {"keys": {"XF86LaunchA": "evil", "XF86LaunchB": [], '
                                                  '"XF86Search": "command"}, "commands": {"XF86Search": 7}, '
                                                  '"mac_layout": "yes", "own_variants": {"de": "x\\"}}\n')
        s = kc.effective()
        self.assertEqual(s["keys"]["XF86LaunchA"], "apps")
        self.assertEqual(s["keys"]["XF86LaunchB"], "menu")
        self.assertEqual(s["keys"]["XF86Search"], "menu")
        self.assertIsNone(s["mac_layout"])
        self.assertEqual(s["own_variants"], {})


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

    def test_hyprland_unreachable_puts_everything_back(self):
        self.hypr.down = True
        self.assertEqual(kc.main(["set", "key.XF86LaunchA=menu"]), 1)
        self.assertFalse((self.dir / "mackeyboard.lua").exists())

    def test_old_plugins_block_stops_the_write(self):
        self.bindings.write_text("-- >>> io.github.2strange.mac-fnkeys >>>\nold\n-- <<< io.github.2strange.mac-fnkeys <<<\n")
        self.assertEqual(kc.main(["set", "key.XF86LaunchA=menu"]), kc.EXIT_FOREIGN)
        self.assertFalse((self.dir / "mackeyboard.lua").exists())
        self.assertNotIn(kc.MARK_BEGIN, self.bindings.read_text())

    def test_reset_removes_a_symlink_not_its_target(self):
        real = self.dir / "dotfiles.lua"
        real.write_text("-- state: {}\n")
        (self.dir / "mackeyboard.lua").symlink_to(real)
        self.assertEqual(kc.main(["reset"]), 0)
        self.assertTrue(real.exists())
        self.assertFalse((self.dir / "mackeyboard.lua").is_symlink())

    def test_failed_write_through_a_symlink_restores_link_and_target(self):
        real = self.dir / "dotfiles.lua"
        real.write_text("-- state: {}\nkeep\n")
        (self.dir / "mackeyboard.lua").symlink_to(real)
        self.hypr.fail = True
        self.assertEqual(kc.main(["set", "key.XF86LaunchA=menu"]), 1)
        self.assertTrue((self.dir / "mackeyboard.lua").is_symlink())
        self.assertEqual(real.read_text(), "-- state: {}\nkeep\n")
        self.hypr.fail, self.hypr.down = False, True
        self.assertEqual(kc.main(["reset"]), 1)  # reset fails too (Hyprland unreachable): the link comes back
        self.assertTrue((self.dir / "mackeyboard.lua").is_symlink())

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

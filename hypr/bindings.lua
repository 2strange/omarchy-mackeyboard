-- Hyprland bindings for the MacBook function row in media mode (fnmode=1), and the Mac layout.
--
-- Loaded from ~/.config/hypr/bindings.lua by the block scripts/setup (or keyboard-config.py on its
-- first change) adds. Omarchy already binds F1/F2 (brightness), F5/F6 on Intel Macs (keyboard
-- light), and F7-F12 (media, volume). The special keys that differ between Mac generations are
-- set in the plugin's menu and written to ~/.config/hypr/mackeyboard.lua; until then these
-- defaults apply.
--
-- F6 on Apple Silicon sends KEY_SLEEP. The plugin service holds a logind suspend-key inhibitor
-- while media mode is active so this binding runs instead of a suspend.

local generated = os.getenv("HOME") .. "/.config/hypr/mackeyboard.lua"
local generated_file = io.open(generated)
if generated_file then
  generated_file:close()
  dofile(generated)
else
  o.bind("XF86LaunchA", "Mission Control", "omarchy-menu toggle apps", { locked = true })
  o.bind("XF86Search", "Spotlight", "omarchy-menu toggle", { locked = true })
  -- Intel MacBooks (e.g. MacBookPro11,3) send KEY_DASHBOARD (Launchpad) on F4 instead of Spotlight.
  o.bind("XF86LaunchB", "Launchpad", "omarchy-menu toggle", { locked = true })
  o.bind_toggle("XF86Sleep", "Do Not Disturb", "notification-silencing", { locked = true })
  if o.cmd_present("voxtype") then o.bind("XF86Dictate", "Toggle dictation", "voxtype record toggle") end
end

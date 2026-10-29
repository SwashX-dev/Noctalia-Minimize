--!nonstrict
local client = require("./client.luau")
shortcut.setLabel("Minimize active window")
shortcut.setIcon("window-minimize")
shortcut.setEnabled(client.enabled())
function onClick() client.minimize() end

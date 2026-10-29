--!nonstrict
local client = require("./client.luau")
barWidget.setGlyph("window-minimize")
barWidget.setTooltip("Minimize active window · Right-click for minimized windows")
function onClick() client.minimize() end
function onRightClick()
    if client.enabled() then noctalia.togglePanel("local/minimizer:windows") end
end

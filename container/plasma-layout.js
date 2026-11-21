function asList(value) {
    if (Array.isArray(value)) {
        return value;
    }
    if (typeof value === "string" && value.length > 0) {
        return value.split(",");
    }
    return [];
}

var taskManagerConfigured = false;
var systemTrayConfigured = false;
var digitalClockConfigured = false;
var systemTrayPanel = null;
var panelIds = panels();

for (var i = 0; i < panelIds.length; i++) {
    var panel = panelIds[i];
    var widgetIds = panel.widgetIds;
    for (var j = 0; j < widgetIds.length; j++) {
        var widget = panel.widgetById(widgetIds[j]);
        if (
            widget.type === "org.kde.plasma.taskmanager" ||
            widget.type === "org.kde.plasma.icontasks"
        ) {
            widget.currentConfigGroup = ["General"];
            widget.writeConfig("launchers", "applications:reset-session.desktop");
            widget.reloadConfig();
            taskManagerConfigured = true;
        } else if (widget.type === "org.kde.plasma.digitalclock") {
            digitalClockConfigured = true;
        } else if (widget.type === "org.kde.plasma.systemtray") {
            var systrayId = widget.readConfig("SystrayContainmentId");
            if (systrayId) {
                var systray = desktopById(systrayId);
                systray.currentConfigGroup = ["General"];
                var knownItems = asList(systray.readConfig("knownItems", []));
                var alwaysEnabledItems = [
                    "org.kde.plasma.volume",
                    "org.kde.plasma.clipboard",
                ];
                var disabledItems = [
                    "org.kde.plasma.cameraindicator",
                    "org.kde.plasma.devicenotifier",
                    "org.kde.plasma.keyboardlayout",
                    "org.kde.plasma.keyboardindicator",
                    "org.kde.plasma.diskquota",
                    "org.kde.plasma.inputmethod",
                    "org.kde.plasma.mediacontroller",
                    "org.kde.plasma.notifications",
                    "org.kde.plasma.trash",
                    "org.kde.plasma.weather",
                ];
                var hiddenItems = knownItems.filter(function (item) {
                    return (
                        alwaysEnabledItems.indexOf(item) === -1 &&
                        disabledItems.indexOf(item) === -1
                    );
                });
                systray.writeConfig("scaleIconsToFit", true);
                systray.writeConfig("extraItems", alwaysEnabledItems);
                systray.writeConfig("shownItems", ["org.kde.plasma.volume"]);
                systray.writeConfig("hiddenItems", hiddenItems);
                systray.writeConfig("disabledStatusNotifiers", disabledItems);
                systray.reloadConfig();
                systemTrayConfigured = true;
                systemTrayPanel = panel;
            }
        }
    }
}

if (!digitalClockConfigured && systemTrayPanel) {
    systemTrayPanel.addWidget("org.kde.plasma.digitalclock");
    digitalClockConfigured = true;
}

print(
    taskManagerConfigured && systemTrayConfigured && digitalClockConfigured
        ? "configured"
        : "waiting"
);

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
var panelIds = panels();

for (var i = 0; i < panelIds.length; i++) {
    var panel = panelIds[i];
    var widgetIds = panel.widgetIds;
    for (var j = 0; j < widgetIds.length; j++) {
        var widget = panel.widgetById(widgetIds[j]);
        if (widget.type === "org.kde.plasma.taskmanager") {
            widget.currentConfigGroup = ["General"];
            widget.writeConfig("launchers", "applications:reset-session.desktop");
            widget.reloadConfig();
            taskManagerConfigured = true;
        } else if (widget.type === "org.kde.plasma.systemtray") {
            var systrayId = widget.readConfig("SystrayContainmentId");
            if (systrayId) {
                var systray = desktopById(systrayId);
                systray.currentConfigGroup = ["General"];
                var knownItems = asList(systray.readConfig("knownItems", []));
                var hiddenItems = knownItems.filter(function (item) {
                    return (
                        item !== "org.kde.plasma.volume" &&
                        item !== "org.kde.plasma.clipboard"
                    );
                });
                systray.writeConfig("extraItems", [
                    "org.kde.plasma.volume",
                    "org.kde.plasma.clipboard",
                ]);
                systray.writeConfig("shownItems", ["org.kde.plasma.volume"]);
                systray.writeConfig("hiddenItems", hiddenItems);
                systray.reloadConfig();
                systemTrayConfigured = true;
            }
        }
    }
}

taskManagerConfigured && systemTrayConfigured ? "configured" : "waiting";

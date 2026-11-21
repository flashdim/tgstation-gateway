var panel = new Panel;
panel.location = "bottom";
panel.alignment = "center";
panel.lengthMode = "fit";
panel.hiding = "autohide";
panel.opacity = "opaque";
panel.floating = false;
panel.height = 64;

var tasks = panel.addWidget("org.kde.plasma.icontasks");
tasks.currentConfigGroup = ["General"];
tasks.writeConfig("launchers", "applications:reset-session.desktop");
panel.addWidget("org.kde.plasma.systemtray");
panel.addWidget("org.kde.plasma.digitalclock");

var desktopsArray = desktopsForActivity(currentActivity());
for (var i = 0; i < desktopsArray.length; i++) {
    desktopsArray[i].wallpaperPlugin = "org.kde.image";
    desktopsArray[i].currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    desktopsArray[i].writeConfig("Image", "file:///usr/share/tgstation-gateway/wallpaper.jpg");
}

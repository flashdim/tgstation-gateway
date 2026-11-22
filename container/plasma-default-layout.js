var panel = new Panel;
panel.location = "bottom";
panel.alignment = "center";
panel.lengthMode = "fit";
panel.hiding = "dodgewindows";
panel.opacity = "opaque";
panel.floating = false;
panel.height = 64;

var tasks = panel.addWidget("org.kde.plasma.taskmanager");
tasks.currentConfigGroup = ["General"];
tasks.writeConfig("launchers", "applications:reset-session.desktop");
tasks.writeConfig("maxTextLines", 1);
panel.addWidget("org.kde.plasma.systemtray");
panel.addWidget("org.kde.plasma.digitalclock");

var desktopsArray = desktopsForActivity(currentActivity());
for (var i = 0; i < desktopsArray.length; i++) {
    desktopsArray[i].wallpaperPlugin = "org.kde.slideshow";
    desktopsArray[i].currentConfigGroup = ["Wallpaper", "org.kde.slideshow", "General"];
    desktopsArray[i].writeConfig("SlidePaths", "/usr/share/tgstation-gateway/wallpapers");
    desktopsArray[i].writeConfig("Color", "0,0,0");
}

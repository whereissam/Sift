import { Config } from "@remotion/cli/config";

// Share the app's logo (frontend/public/logo.png) instead of keeping a copy.
Config.setPublicDir("../frontend/public");
Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);

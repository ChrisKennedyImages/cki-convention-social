import { Config } from "@remotion/cli/config";

// The suite renders a look with a public dir of its own per reel (convention_social/render/reel_looks.py): the reel's
// photos, its track and links to fonts/ and textures/ here, passed as --public-dir. Nothing is read from elsewhere.
Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(92);
Config.setOverwriteOutput(true);

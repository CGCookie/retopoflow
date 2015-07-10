import os
import bpy
import bpy.utils.previews

icon_collections = {}

def load_icons():
	rf_icons = bpy.utils.previews.new()

	icons_dir = os.path.join(os.path.dirname(__file__), "icons")

	rf_icons.load(
	"rf_contours_icon",
	os.path.join(icons_dir, "contours_32.png"),
	'IMAGE')
	rf_icons.load(
	"rf_polystrips_icon",
	os.path.join(icons_dir, "polystrips_32.png"),
	'IMAGE')

	icon_collections["main"] = rf_icons

	return icon_collections["main"]
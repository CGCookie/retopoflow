import os
import bpy
import bpy.utils.previews

icon_collections = {}
icons_loaded = False

def load_icons():
	global icon_collections
	global icons_loaded

	if icons_loaded: return icon_collections["main"]

	rf_icons = bpy.utils.previews.new()

	icons_dir = os.path.join(os.path.dirname(__file__), "icons")

	rf_icons.load( "rf_contours_icon", os.path.join(icons_dir, "contours_32.png"), 'IMAGE')
	rf_icons.load( "rf_polystrips_icon", os.path.join(icons_dir, "polystrips_32.png"), 'IMAGE')
	rf_icons.load( "rf_polypen_icon", os.path.join(icons_dir, "polypen_32.png"), 'IMAGE')
	rf_icons.load( "rf_tweak_icon", os.path.join(icons_dir, "tweak_32.png"), 'IMAGE')
	rf_icons.load( "rf_loopcut_icon", os.path.join(icons_dir, "loop_cut_32.png"), 'IMAGE')
	rf_icons.load( "rf_loopdelete_icon", os.path.join(icons_dir, "loop_delete_32.png"), 'IMAGE')
	rf_icons.load( "rf_loopslide_icon", os.path.join(icons_dir, "loop_slide_32.png"), 'IMAGE')

	icon_collections["main"] = rf_icons
	icons_loaded = True

	return icon_collections["main"]

def clear_icons():
	global icons_loaded
	for icon in icon_collections.values():
		bpy.utils.previews.remove(icon)
	icon_collections.clear()
	icons_loaded = False
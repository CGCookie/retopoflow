# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import bpy
from .addon_updater import Updater as updater
from bpy.app.handlers import persistent

# -----------------------------------------------------------------------------
# Example operators utilizing Updater
# -----------------------------------------------------------------------------

# simple popup for prompting checking for update & allowing to install if available
class addon_updater_install_popup(bpy.types.Operator):
	"""Check and install update if available"""
	bl_label = "Update {x} addon".format(x=updater.addon)
	bl_idname = updater.addon+".updater_install_popup"
	bl_description = "Popup menu to check and display current updates available"

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self) # can force width, icon?

	def draw(self, context):
		layout = self.layout
		if updater.update_ready == True:
			layout.label("Update ready!")
			layout.label("Press okay to install v"+str(updater.update_version))
		elif updater.update_ready == False:
			layout.label("No updates available")
			layout.label("Press okay to dismiss dialog")
			# add option to force install
		else:
			# case: updater.update_ready = None
			# we have not yet checked for the update
			layout.label("Check for update now?")

		# potentially in future, could have UI for 'check to select old version'
		# to revert back to.

	def execute(self,context):

		if updater.update_ready == True:
			updater.run_update(force=False)
		elif updater.update_ready == None:
			(update_ready, version, link) = updater.check_for_update(now=True)
			# re-launch this dialog
			atr = addon_updater_install_popup.bl_idname.split(".")
			getattr(getattr(bpy.ops, atr[0]),atr[1])('INVOKE_DEFAULT')
			#bpy.ops.retopoflow.updater_install_popup('INVOKE_DEFAULT')

		else:
			print("Doing nothing, not ready for update")
		return {'FINISHED'}


# User preference check-now operator
class addon_updater_check_now(bpy.types.Operator):
	bl_label = "Check now for "+updater.addon+" update"
	bl_idname = updater.addon+".updater_check_now"
	bl_description = "Check now for an update to the {x} addon".format(
														x=updater.addon)

	def execute(self,context):

		# could be okay if not async,
		# but ideally launches/connects to the Daemon thread
		try:
			check_for_update_nonthreaded(context)
		except:
			self.report({'ERROR'}, "Encountered problem looking for update")

		return {'FINISHED'}


class addon_updater_update_now(bpy.types.Operator):
	bl_label = "Update "+updater.addon+" addon now"
	bl_idname = updater.addon+".updater_update_now"
	bl_description = "Check now for an update to the {x} addon".format(
														x=updater.addon)


	def execute(self,context):

		if updater.update_ready == True:
			# if it fails, offer to open the website instead
			try:
				updater.run_update(force=False)
			except:
				atr = addon_updater_install_manually.bl_idname.split(".")
				getattr(getattr(bpy.ops, atr[0]),atr[1])('INVOKE_DEFAULT')
		elif updater.update_ready == None:
			(update_ready, version, link) = updater.check_for_update(now=True)
			# re-launch this dialog
			atr = addon_updater_install_popup.bl_idname.split(".")
			getattr(getattr(bpy.ops, atr[0]),atr[1])('INVOKE_DEFAULT')
			
			#bpy.ops.retopoflow.updater_install_popup('INVOKE_DEFAULT')


		else:
			print("Doing nothing, not ready for update")
			self.report({'ERROR'}, "Encountered problem looking for update")

		return {'FINISHED'}



class addon_updater_install_manually(bpy.types.Operator):
	"""As a fallback, direct the user to download the addon manually"""
	bl_label = "Install update manually"
	bl_idname = updater.addon+".updater_install_manually"
	bl_description = "Installing update failed, proceed manually"

	# not an "okay" to execut, but just oeprators
	def invoke(self, context, event):
		return context.window_manager.invoke_popup(self)

	def draw(self, context):
		layout = self.layout
		# use a "failed flag"? it show this label if the case failed.
		if False:
			layout.label("There was an issue trying to auto-install")
		else:
			layout.label("Install the addon manually")
			layout.label("Press the download button below and install")
			layout.label("the zip file like a normal addon.")

		# if check hasn't happened, ie accidentally called this menu
		# allow to check here

		row = layout.row()

		if updater.update_link != None:
			row.operator("wm.url_open",text="Direct download").url=updater.update_link
		else:
			row.operator("wm.url_open",text="(failed to retreive)")
			row.enabled = False

			if updater.website != None:
				row = layout.row()
				row.label("Grab update from account")

				row.operator("wm.url_open",text="Open website").url=updater.website
			else:
				row = layout.row()

				row.label("See source website to download the update")

	def execute(self,context):

		return {'FINISHED'}


class addon_updater_updated_successful(bpy.types.Operator):
	"""As a fallback, direct the user to download the addon manually"""
	bl_label = "Update Successful"
	bl_idname = updater.addon+".updater_update_successful"
	bl_description = "Update installation was successful"

	# not an "okay" to execut, but just oeprators
	def invoke(self, context, event):
		return context.window_manager.invoke_popup(self)

	def draw(self, context):
		layout = self.layout
		# use a "failed flag"? it show this label if the case failed.
		layout.label("TBD: make a better 'hey it worked!' message popup")
	
	def execut(self, context):
		return {'FINISHED'}


@persistent
def updater_run_success_popup(scene):
	print("Update successful, showing popup.")
	atr = addon_updater_updated_successful.bl_idname.split(".")
	getattr(getattr(bpy.ops, atr[0]),atr[1])('INVOKE_DEFAULT')
	try:
		bpy.app.handlers.scene_update_post.remove(updater_run_success_popup)
	except:
		pass



# -----------------------------------------------------------------------------
# Utility and example includable UI integrations
# -----------------------------------------------------------------------------



# UI to place e.g. at the end of a UI panel where to notify update available
def update_notice_box_ui(self, context):
	if updater.update_ready != True: return

	settings = context.user_preferences.addons[__package__].preferences
	layout = self.layout
	box = layout.box()
	col = box.column(align=True)
	col.label("Update ready!",icon="ERROR")
	col.operator("wm.url_open", text="Open website").url = updater.website
	#col.operator("wm.url_open",text="Direct download").url=updater.update_link
	# atr = addon_updater_install_manually.bl_idname.split(".")
	# 			getattr(getattr(bpy.ops, atr[0]),atr[1])('INVOKE_DEFAULT')
	col.operator(addon_updater_install_manually.bl_idname, "Install manually")
	col.operator(addon_updater_update_now.bl_idname,
					"Update now", icon="LOOP_FORWARDS") # could also do popup instead



# create a function that can be run inside of a user preferences panel for prefs UI
# place inside UI draw using: addon_updater_ops.updaterSettingsUI(self, context)
# or by: addon_updater_ops.updaterSettingsUI(context)
def update_settings_ui(self, context):
	settings = context.user_preferences.addons[__package__].preferences

	layout = self.layout
	box = layout.box()

	# auto-update settings
	box.label("Updater Settings")
	row = box.row()
	split = row.split(percentage=0.3)
	subcol = split.column()
	subcol.prop(settings, "auto_check_update")
	subcol = split.column()

	if settings.auto_check_update==False: subcol.enabled = False
	subrow = subcol.row()
	subrow.label("Interval between checks")
	subrow = subcol.row(align=True)
	checkcol = subrow.column(align=True)
	checkcol.prop(settings,"updater_intrval_months")
	checkcol = subrow.column(align=True)
	checkcol.prop(settings,"updater_intrval_days")
	checkcol = subrow.column(align=True)
	checkcol.prop(settings,"updater_intrval_hours")
	checkcol = subrow.column(align=True)
	checkcol.prop(settings,"updater_intrval_minutes")


	# checking / managing updates
	row = box.row()
	col = row.column()
	col.scale_y = 2
	if updater.update_ready == None and updater.async_checking == False:
		col.operator(addon_updater_check_now.bl_idname, "Check now")
	elif updater.update_ready == None: # async is running
		col.enabled = False
		col.operator(addon_updater_check_now.bl_idname, "Checking for update....")
	else:
		col.operator(addon_updater_update_now.bl_idname, "Update now to "+str(updater.update_version))
	# row.label("Updated not checked for yet")

	col = row.column(align=True)
	col.operator(addon_updater_check_now.bl_idname, "Reinstall / install old verison")
	col.operator(addon_updater_check_now.bl_idname, "Restore addon backup (date)")

	#if updater.update_ready == False and updater._async_checking == False:


# function for asynchronous background check, which *could* be called on register
def check_for_update_background(context):

	if updater.update_ready != None or updater.async_checking == True:
		# Check already happened
		# Used here to just avoid constant applying settings below
		return 

	# apply the UI settings
	settings = context.user_preferences.addons[__package__].preferences
	updater.set_check_interval(enable=settings.auto_check_update,
				months=settings.updater_intrval_months,
				days=settings.updater_intrval_days,
				hours=settings.updater_intrval_hours,
				minutes=settings.updater_intrval_minutes
				) # optional, if auto_check_update 
	updater.check_for_update_async()


# a function that can be placed in front of other operators to launch when pressed
def check_for_update_nonthreaded(context):

	# only check if it's ready, ie after the time interval specified
	# should be the async wrapper call here

	settings = context.user_preferences.addons[__package__].preferences
	updater.set_check_interval(enable=settings.auto_check_update,
				months=settings.updater_intrval_months,
				days=settings.updater_intrval_days,
				hours=settings.updater_intrval_hours,
				minutes=settings.updater_intrval_minutes
				) # optional, if auto_check_update 

	(update_ready, version, link) = updater.check_for_update(now=False)
	if update_ready == True:
		atr = addon_updater_install_popup.bl_idname.split(".")
		getattr(getattr(bpy.ops, atr[0]),atr[1])('INVOKE_DEFAULT')
		# or manually update the name of the operator bl_label
		#bpy.ops.{the updater.addon+".updater_install_popup" text}('INVOKE_DEFAULT')
	else:
		if updater.verbose: print("No update ready")
		self.report({'INFO'}, "No update ready")


# -----------------------------------------------------------------------------
# Register, should be run in the register module itself
# -----------------------------------------------------------------------------



# registering the operators in this module
def register(bl_info):

	print("Running updater reg")

	updater.user = "TeamDeverse" # previously "cgcookie"
	updater.repo = "retopoflow"
	updater.website = "https://cgcookiemarkets.com/all-products/retopoflow/" # optional
	updater.use_releases = False # ie use tags instead of releases, default True
	updater.current_version = bl_info["version"]
	#updater.set_check_interval(enable=False,months=0,days=0,hours=0,minutes=2) # optional
	updater.verbose = True # optional, consider turning off for production or allow as option
	# updater.updater_path = # set path of updater folder, by default:
	#			/addons/{__package__}/{__package__}_updater
	updater.backup_current = True # True by default

	
	# best practice to ensure failing doesn't create issue with register,
	# always enclose in try/except in production
	
	# try:
		# result = updater.check_for_update()
	# except:
	# 	print("Failed to check for update")
	

	# # **definitely** shouldn't do this, ask permission first e.g. in popup.
	# # but, no values need to be passed in.. all stored in the class.
	# # In fact, cannot run this here.. context is prevented. 
	# updater.run_update(force=False)


	bpy.utils.register_class(addon_updater_install_popup)
	bpy.utils.register_class(addon_updater_check_now)
	bpy.utils.register_class(addon_updater_update_now)
	bpy.utils.register_class(addon_updater_install_manually)
	bpy.utils.register_class(addon_updater_updated_successful)
	

	# special situation: we JUST updated the addon, show a popup
	# to tell the user it worked
	saved_state = updater.json
	if saved_state != None and "just_updated" in saved_state and saved_state["just_updated"] == True:
		if updater_run_success_popup not in bpy.app.handlers.scene_update_post:
			bpy.app.handlers.scene_update_post.append(updater_run_success_popup)
	
	
	# bpy.utils.register_class(UpdaterPreferences)



def unregister():
	""
	bpy.utils.unregister_class(addon_updater_install_popup)
	bpy.utils.unregister_class(addon_updater_check_now)
	bpy.utils.unregister_class(addon_updater_update_now)
	bpy.utils.unregister_class(addon_updater_install_manually)
	bpy.utils.unregister_class(addon_updater_updated_successful)

	# bpy.utils.unregister_class(UpdaterPreferences) # used in actual prefs place

	
	# kill any threads

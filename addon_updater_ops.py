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

# -----------------------------------------------------------------------------
# Example and includable UI integration of the addon updater module
# -----------------------------------------------------------------------------

# popup for prompting checking for update & allowing to install if available
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
			#getattr(bpy.ops, addon_updater_install_popup.bl_idname)('INVOKE_DEFAULT')
			bpy.ops.retopoflow.updater_install_popup('INVOKE_DEFAULT')


		else:
			print("Doing nothing, not ready for update")
		return {'FINISHED'}


# create a function that can be run inside of a user preferences panel for prefs UI
# place inside UI draw using: addon_updater_ops.updaterSettingsUI(self, context)
# or by: addon_updater_ops.updaterSettingsUI(context)
def updaterSettingsUI(self, context):
	self.layout.label("Auto-update settings")


# function for asynchronous background check, which *could* be called on register
# TBD


# a function that can be placed in front of other operators to launch when pressed
# use by calling: addon_updater_ops.checkForUpdate()
def checkForUpdate():

	# only check if it's ready, ie after the time interval specified
	(update_ready, version, link) = updater.check_for_update(now=False)
	if update_ready == True:
		print("Launch the popup")
		# addon_updater_install_popup.bl_idname

		getattr(bpy.ops, addon_updater_install_popup.bl_idname)('INVOKE_DEFAULT')
		# or manually update the name of the operator bl_label
		#bpy.ops.{the updater.addon+".updater_install_popup" text}('INVOKE_DEFAULT')
	else:
		print("Update not ready")


# registering the operators in this module
def register():
	#bpy.utils.register_module(addon_updater_install_popup)
	""


def unregister():
	#bpy.utils.unregister_module(addon_updater_install_popup)
	""

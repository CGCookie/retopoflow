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


"""
[ todo, create better base usage instructions here ]
Minor parts of this code are derived from the PyGithub repository
Example base usage:
my_updater = addon_updater.Updater("git_username","repository",use_releases=True)
my_updater.release_last # will get the most recent release info, dicitonary
"""

import urllib.request
import urllib
import os
import json
import zipfile
import shutil


DEFAULT_API_URL = "https://api.github.com" # plausibly could be some other system
DEFAULT_TIMEOUT = 10
DEFAULT_PER_PAGE = 30


class Updater(object):
	"""
	This is the main class to instantiate
	"""

	# constructor
	def __init__(self, user, repo, api_url=DEFAULT_API_URL, timeout=DEFAULT_TIMEOUT, 
				use_releases=True, current_version = None, stage_path="//"):
		
		"""
		:param user: string # name of the user owning the repository
		:param repo: string # name of the repository
		:param api_url: string # should just be the github api link
		:param timeout: integer # request timeout
		:param use_releases: bool # else uses tags for release version checking
		:param current_version: tuple # typically 3 values meaning the version #
		"""

		self._user = user
		self._repo = repo
		self._api_url = api_url
		self._current_version = current_version
		self._tags = []
		self._tag_latest = None
		self._tag_names = []
		self._releases = []
		self._release_latest = None
		self._stage_path = stage_path


	# -------------------------------------------------------------------------
	# Getters and setters
	# -------------------------------------------------------------------------


	@property
	def user(self):
		return self._user
	@user.setter
	def user(self, value):
		self._user = value

	@property
	def repo(self):
		return self._repo
	@repo.setter
	def repo(self, value):
		self._repo = value

	@property
	def api_url(self):
		return self._pai_url
	@api_url.setter
	def api_url(self, value):
		if self.check_is_url(value) == False:
			raise ValueError("Not a valid URL: " + value)
		self._api_url = value

	@property
	def tags(self):
		if self._tags == []:
			self._tags = self.get_tags() # full json
		tag_names = self.get_tag_names() # just name title

		return tag_names

	@property
	def tag_latest(self):
		if self._tag_latest == None:
			self._tags = self.get_tags()
			self._tag_latest = self._tags[0]
		return self._tag_latest["name"]

	@property
	def releases(self):
		if self._releases == []:
			self._releases = self.get_releases()
		return self._releases

	@property
	def release_latest(self):
		if self._releases_latest == None:
			self._releases = self.get_releases()
			self._release_latest = self._releases[0]
		return self._release_latest

	@property
	def current_version(self):
		return self._current_version

	@current_version.setter
	def current_version(self,tuple_values):
		if type(tuple_values) is not tuple:
			raise ValueError("Not a tuple! current_version must be a tuple of integers")
		for i in tuple_values:
			if type(i) is not int:
				raise ValueError("Not an integer! current_version must be a tuple of integers")
		self._current_version = tuple_values


	# -------------------------------------------------------------------------
	# Paramater validation related functions
	# -------------------------------------------------------------------------


	def check_is_url(self,url):
		if "http://" not in url:
			return False
		if "." not in url:
			return False
		return True

	def get_tag_names(self):
		tag_names = []
		for tag in self._tags:
			tag_names.append(tag["name"])
		return tag_names

	# other class stuff

	def __repr__(self):
		return "<Module updater from {a}>".format(a=__file__)

	def __str__(self):
		return "Updater, with user:{a}, repository:{b}, url:{c}".format(a=self._user,
									b=self._repo, c=self.form_repo_url())


	# -------------------------------------------------------------------------
	# API-related functions
	# -------------------------------------------------------------------------

	def form_repo_url(self):
		return DEFAULT_API_URL+"/repos/"+self.user+"/"+self.repo


	def get_tags(self):
		request = "/repos/"+self.user+"/"+self.repo+"/tags"
		# print("Request url: ",request)
		return self.get_api(request) # check error responses?


	# all API calls to base url
	def get_api_raw(self, url):
		request = urllib.request.Request(DEFAULT_API_URL + url)
		try:
			result = urllib.request.urlopen(request)
		except urllib.error.HTTPError as e:
			raise ValueError("HTTPError, code: ",e.code)
			# return or raise error?
		except urllib.error.URLError as e:
			raise ValueError("URLError, reason: ",e.reason)
			# return or raise error?
		else:
			result_string = result.read()
			result.close()
			return result_string.decode()
		# if we didn't get here, return or raise something else
		
		
	# result of all api calls, decoded into json format
	def get_api(self, url):
		# return the json version
		get = None
		try:
			get = self.get_api_raw(url)
			# print(get)
		except:
			raise ValueError("Error in api get request")
		try:
			return json.JSONDecoder().decode( get )
		except:
			raise ValueError("JSON decoding error")


	# create a working directory and download the new files
	def stage_repository(self, url):

		# first make/clear the staging folder
		# ensure our folder is always "clean"
		local = self._stage_path
		if local == "//":
			local = os.path.dirname(os.path.realpath(__file__))

		local = os.path.join(local, "update_staging")
		error = False
		if os.path.isdir(local) == True:
			# try/except for permission errors or other OS errors!
			try:
				shutil.rmtree(local)
				print("remove?")
			except:
				print("Error, couldn't remove existing staging directory")
				error = True
		try:
			os.makedirs(local)
		except:
			print("Error, couldn't make staging directory")
			error = True
		
		if error == True:
			print("Aborting update") # return error instead, with text standard
			return -1

		

		urllib.request.urlretrieve(url, os.path.join(local,"source.zip"))
		return 0


	# -------------------------------------------------------------------------
	# Other non-api functions and setups
	# -------------------------------------------------------------------------


	def version_tuple_from_text(self,text):

		# should go through string and remove all non-integers, 
		# and for any given break split into a different section

		segments = []
		tmp = ''
		for l in text:
			if l.isdigit()==False:
				if len(tmp)>0:
					segments.append(int(tmp)) # int(tmp)
					tmp = ''
			else:
				tmp+=l
		if len(tmp)>0:
			segments.append(int(tmp)) # int(tmp)

		if len(segments)==0:
			raise ValueError("Error in parsing version text")

		return tuple(segments) # turn into a tuple


	def check_for_update(self):
		if self._current_version == None:
			raise ValueError("No current_version property set for comparison")

		# check if using tags or releases
		new_version = self.version_tuple_from_text(self._tag_latest["name"])
		link = self._tags[0]["zipball_url"] # best way?
		if new_version != self._current_version:
			return (True, new_version, link)

		# need to make clean version of git tag/release name.

		return (False, None)



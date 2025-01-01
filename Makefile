# ---------------------------------------------------------------
# Makefile for RetopoFlow
# Jonathan Williamson - <jonathan@cgcookie.com>

# Originally created by Diego Gangl - <diego@sinestesia.co>
# ---------------------------------------------------------------



#########################################################
# settings

# TODO: warn if profiling is enabled!
# see https://ftp.gnu.org/old-gnu/Manuals/make-3.79.1/html_chapter/make_6.html

# scripts
BLINFO_VAL        = $(shell pwd)/scripts/get_blinfo_value.py
DEBUG_CLEANUP     = $(shell pwd)/addon_common/scripts/strip_debugging.py
UPDATE_COPYRIGHT  = $(shell pwd)/addon_common/scripts/update_copyright_date.py
DOCS_REBUILD      = $(shell pwd)/scripts/prep_help_for_online.py
CREATE_THUMBNAILS = $(shell pwd)/scripts/create_thumbnails.py
BLENDER           = ~/software/blender/blender

# name, version, and release are pulled from bl_info in __init__.py file
NAME    = "$(shell $(BLINFO_VAL) name)"
VERSION = "$(shell $(BLINFO_VAL) version)"
RELEASE = "$(shell $(BLINFO_VAL) warning Official)"

VVERSION = "v$(VERSION)"
ifeq ($(RELEASE), "official")
	ZIP_VERSION = "$(VVERSION)"
else
	ZIP_VERSION = "$(VVERSION)-$(RELEASE)"
endif
GIT_TAG_MESSAGE = "This is the $(RELEASE) release for RetopoFlow $(VVERSION)"

BUILD_DIR         = $(shell pwd)/../retopoflow_release
INSTALL_DIR       = ~/.config/blender/addons
CGCOOKIE_BUILT    = $(NAME)/.cgcookie
ZIP_GH            = $(NAME)_$(ZIP_VERSION)-GitHub.zip
ZIP_BM            = $(NAME)_$(ZIP_VERSION)-BlenderMarket.zip


.DEFAULT_GOAL 	:= info

# .PHONY: _build-pre _build-post


#########################################################
# information

info:
	@echo "Information:"
	@echo "  Product:      "$(NAME)" "$(ZIP_VERSION)
	@echo "  Build Path:   "$(BUILD_DIR)
	@echo "  Folder:       "$(NAME)
	@echo "  Install Path: "$(INSTALL_DIR)
	@echo "Targets:"
	@echo "  development:   clean, check, gittag, install"
	@echo "  documentation: build-docs, serve-docs, clean-docs, build-thumbnails"
	@echo "  build zips:    build, build-github, build-blendermarket"


#########################################################
# utilities

clean:
	rm -rf $(BUILD_DIR)
	@echo "Release folder deleted"

update-copyright:
	python3 $(UPDATE_COPYRIGHT)

#########################################################
# documentation targets

build-docs:
	# rebuild online docs
	python3 $(DOCS_REBUILD)
	cd docs && bundle add webrick && bundle update

serve-docs:
	cd docs && bundle exec jekyll serve

clean-docs:
	cd docs && bundle exec jekyll clean


#########################################################
# build targets

blinfo:
	@echo "Updating bl_info in __init__.py by running Blender with --background"
	$(BLENDER) --background

check:
	# check that we don't have case-conflicting filenames (ex: utils.py Utils.py)
	# most Windows setups have issues with these
	./scripts/detect_filename_case_conflicts.py

build-thumbnails:
	# create thumbnails
	cd help/images && python3 $(CREATE_THUMBNAILS)

build:
	make _build-docs _build-common _build-github _build-blendermarket
	@echo "\n\n"$(NAME)" "$(VVERSION)" is ready"

build-github:
	make _build-common _build-github
	@echo "\n\n"$(NAME)" "$(VVERSION)" is ready"

build-blendermarket:
	make _build-common _build-blendermarket
	@echo "\n\n"$(NAME)" "$(VVERSION)" is ready"

# helper targets

_build-docs:
	make build-thumbnails build-docs

_build-common:
	make check blinfo
	mkdir -p $(BUILD_DIR)/$(NAME)
	# copy files over to build folder
	# note: rsync flag -a == archive (same as -rlptgoD)
	rsync -av --progress . $(BUILD_DIR)/$(NAME) --exclude-from="Makefile_excludes"
	# run debug cleanup
	cd $(BUILD_DIR) && python3 $(DEBUG_CLEANUP) "YES!"

_build-github:
	# touch file so that we know it was packaged by us and zip it!
	cd $(BUILD_DIR) && echo "This file indicates that CG Cookie built this version of RetopoFlow for release on GitHub." > $(CGCOOKIE_BUILT)
	cd $(BUILD_DIR) && zip -r $(ZIP_GH) $(NAME)

_build-blendermarket:
	# touch file so that we know it was packaged by us and zip it!
	cd $(BUILD_DIR) && echo "This file indicates that CG Cookie built this version of RetopoFlow for release on Blender Market." > $(CGCOOKIE_BUILT)
	cd $(BUILD_DIR) && zip -r $(ZIP_BM) $(NAME)


#########################################################
# installing target

install:
	rm -r $(INSTALL_DIR)/$(NAME)
	cp -r $(BUILD_DIR)/$(NAME) $(INSTALL_DIR)/$(NAME)

gittag:
	# create a new annotated (-a) tag and push to GitHub
	git tag -a $(VVERSION) -m $(GIT_TAG_MESSAGE)
	git push origin $(VVERSION)

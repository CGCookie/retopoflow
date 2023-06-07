# ---------------------------------------------------------------
# Makefile for RetopoFlow
# Jonathan Williamson - <jonathan@cgcookie.com>

# Originally created by Diego Gangl - <diego@sinestesia.co>
# ---------------------------------------------------------------



# /./././././././././././././././././././././././././././././././
# SETTINGS
# /./././././././././././././././././././././././././././././././

# TODO: warn if profiling is enabled!
# see https://ftp.gnu.org/old-gnu/Manuals/make-3.79.1/html_chapter/make_6.html

# scripts
HIVE_VAL          = $(shell pwd)/scripts/get_hive_value.py
DEBUG_CLEANUP     = $(shell pwd)/addon_common/scripts/strip_debugging.py
DOCS_REBUILD      = $(shell pwd)/scripts/prep_help_for_online.py
CREATE_THUMBNAILS = $(shell pwd)/scripts/create_thumbnails.py
BLENDER           = ~/software/blender/blender

# name, version, and release are pulled from hive.json file
NAME    = "$(shell $(HIVE_VAL) name)"
VERSION = "$(shell $(HIVE_VAL) version)"
RELEASE = "$(shell $(HIVE_VAL) release)"

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

.PHONY: docs


# /./././././././././././././././././././././././././././././././
# TARGETS
# /./././././././././././././././././././././././././././././././


info:
	@echo "Information:"
	@echo "  "$(NAME)" "$(ZIP_VERSION)
	@echo "  Build Path:   "$(BUILD_DIR)
	@echo "  Install Path: "$(INSTALL_DIR)
	@echo "Targets:"
	@echo "  documentation: docs, docs-serve, docs-clean, thumbnails"
	@echo "  development:   clean, check, gittag, install"
	@echo "  build:         build-github, build-blendermarket"

clean:
	rm -rf $(BUILD_DIR)
	@echo "Release folder deleted"


gittag:
	# create a new annotated (-a) tag and push to GitHub
	git tag -a $(VVERSION) -m $(GIT_TAG_MESSAGE)
	git push origin $(VVERSION)

blinfo:
	@echo "Updating bl_info in __init__.py by running Blender with --background"
	$(BLENDER) --background

docs:
	# rebuild online docs
	python3 $(DOCS_REBUILD)

docs-serve:
	cd docs && bundle exec jekyll serve

docs-clean:
	cd docs && bundle exec jekyll clean

check:
	# check that we don't have case-conflicting filenames (ex: utils.py Utils.py)
	# most Windows setups have issues with these
	./scripts/detect_filename_case_conflicts.py

thumbnails:
	# create thumbnails
	cd help && python3 $(CREATE_THUMBNAILS)

build: build-github build-blendermarket
	@echo

build-github: check blinfo thumbnails docs
	mkdir -p $(BUILD_DIR)
	mkdir -p $(BUILD_DIR)/$(NAME)

	# copy files over to build folder
	# note: rsync flag -a == archive (same as -rlptgoD)
	rsync -av --progress . $(BUILD_DIR)/$(NAME) --exclude-from="Makefile_excludes"
	# touch file so that we know it was packaged by us
	cd $(BUILD_DIR) && echo "This file indicates that CG Cookie built this version of RetopoFlow for release on GitHub." > $(CGCOOKIE_BUILT)
	# run debug cleanup
	cd $(BUILD_DIR) && python3 $(DEBUG_CLEANUP) "YES!"
	# create thumbnails
	cd $(BUILD_DIR)/$(NAME)/help && python3 $(CREATE_THUMBNAILS)
	# zip it!
	cd $(BUILD_DIR) && zip -r $(ZIP_GH) $(NAME)

	@echo
	@echo $(NAME)" "$(VVERSION)" is ready"

build-blendermarket: check blinfo thumbnails docs
	mkdir -p $(BUILD_DIR)
	mkdir -p $(BUILD_DIR)/$(NAME)

	# copy files over to build folder
	# note: rsync flag -a == archive (same as -rlptgoD)
	rsync -av --progress . $(BUILD_DIR)/$(NAME) --exclude-from="Makefile_excludes"
	# touch file so that we know it was packaged by us
	cd $(BUILD_DIR) && echo "This file indicates that CG Cookie built this version of RetopoFlow for release on Blender Market." > $(CGCOOKIE_BUILT)
	# run debug cleanup
	cd $(BUILD_DIR) && python3 $(DEBUG_CLEANUP) "YES!"
	# create thumbnails
	cd $(BUILD_DIR)/$(NAME)/help && python3 $(CREATE_THUMBNAILS)
	# zip it!
	cd $(BUILD_DIR) && zip -r $(ZIP_BM) $(NAME)

	@echo
	@echo $(NAME)" "$(VVERSION)" is ready"


install:
	rm -r $(INSTALL_DIR)/$(NAME)
	cp -r $(BUILD_DIR)/$(NAME) $(INSTALL_DIR)/$(NAME)


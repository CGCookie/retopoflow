# ---------------------------------------------------------------
# Makefile for RetopoFlow
# Jonathan Williamson - <jonathan@cgcookie.com>

# Originally created by Diego Gangl - <diego@sinestesia.co>
# ---------------------------------------------------------------



# /./././././././././././././././././././././././././././././././
# SETTINGS
# /./././././././././././././././././././././././././././././././

NAME            = RetopoFlow
VERSION         = v2.0.3
GIT_TAG         = v2.0.3
GIT_TAG_MESSAGE = "Version 2.0.3"

BUILD_DIR       = ../retopoflow_release
ZIP_FILE        = $(NAME)_$(VERSION).zip


# /./././././././././././././././././././././././././././././././
# TARGETS
# /./././././././././././././././././././././././././././././././

.DEFAULT_GOAL  := build

.PHONY: clean gittag build


clean:
	rm -rf $(BUILD_DIR)
	@echo "Release folder deleted"


gittag:
	# create a new annotated (-a) tag and push to GitHub
	git tag -a $(GIT_TAG) -m $(GIT_TAG_MESSAGE)
	git push origin $(GIT_TAG)
	@echo "git tag is pushed"


build:
	# first remove the build folder, in case there are extra files there
	# then, create build folder (if they do not already exist)
	rm -rf $(BUILD_DIR)/$(NAME)
	mkdir -p $(BUILD_DIR)
	mkdir -p $(BUILD_DIR)/$(NAME)

	# rsync flag -a == archive (same as -rlptgoD)
	rsync -av --progress --no-links . $(BUILD_DIR)/$(NAME) --exclude-from="Makefile_excludes"
	cd $(BUILD_DIR) ; zip -r $(ZIP_FILE) $(NAME)

	@echo
	@echo $(NAME)" "$(VERSION)" is ready"

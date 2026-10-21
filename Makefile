.PHONY: help build test clean

# Transitional build workflow for the Android migration.
# The Gradle wrapper may live at the repository root or in android/.
ifneq ($(wildcard gradlew),)
ANDROID_DIR := .
else ifneq ($(wildcard android/gradlew),)
ANDROID_DIR := android
endif

ifeq ($(OS),Windows_NT)
GRADLE := gradlew.bat
else
GRADLE := ./gradlew
endif

help:
	@echo "Offline G2 Android build workflow"
	@echo "  make build   Build the Android debug application"
	@echo "  make test    Run Android unit tests"
	@echo "  make clean   Clean Android build files"
	@echo ""
	@echo "Docker-based build targets have been removed."

build:
ifndef ANDROID_DIR
	@echo "Android project is not present yet. Add the Gradle project before running make build."
else
	cd $(ANDROID_DIR) && $(GRADLE) assembleDebug
endif

test:
ifndef ANDROID_DIR
	@echo "Android project is not present yet. Add the Gradle project before running make test."
else
	cd $(ANDROID_DIR) && $(GRADLE) test
endif

clean:
ifndef ANDROID_DIR
	@echo "Android project is not present yet. Nothing to clean."
else
	cd $(ANDROID_DIR) && $(GRADLE) clean
endif

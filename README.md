# evenG2mount

Offline speech translation and captioning for Even Realities G2 smart glasses.

## Current Direction

The project is transitioning from the original desktop prototype to a native Android architecture.

The target workflow is:

1. Capture speech on an Android phone.
2. Perform speech recognition locally.
3. Translate the recognized text locally.
4. Send captions from the Android application to the G2 glasses over Bluetooth.

The speech-recognition and translation models are still being evaluated. The goal is to keep processing on-device and minimize dependence on external services.

## Development Setup

Android Studio is the primary development environment.

The Android Gradle project may live either:

- at the repository root, or
- inside an `android/` directory.

The Makefile automatically checks both locations.

## Make Commands

`make help` shows the available development commands.

`make build` builds the Android debug application.

`make test` runs Android unit tests.

`make clean` cleans Android build files.

Until the Android Gradle project is added to the repository, these commands exit safely with a message explaining that the Android project is not present yet.

## Repository Components

- `capstone_tests/` - testing and benchmarking work.
- `men-g2-ble-gateway/` - earlier G2 communication prototype retained for reference.
- `whisper.cpp/` - earlier speech-recognition implementation and model testing work.
- `Makefile` - Android-oriented build, test, and clean workflow.

## Development Workflow

Changes should be made on feature branches and reviewed before being merged into `main`.

The current priority is validating the core Android MVP:

speech input -> offline recognition -> offline translation -> G2 caption display

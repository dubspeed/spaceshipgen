#!/bin/bash
# Setup for headless cloud sessions (Ubuntu). Ubuntu's Blender package uses the
# system Python, so the glTF exporter additionally needs python3-numpy.
set -e
apt-get update
apt-get install -y blender python3-numpy

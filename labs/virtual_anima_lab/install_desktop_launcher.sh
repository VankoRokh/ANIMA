#!/usr/bin/env bash
# Install/update a user-only desktop launcher for the standalone Virtual ANIMA Lab.
# Does not install Godot or change ANIMA Core; requires a locally executable Godot.
set -euo pipefail

lab_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$lab_dir/godot"
godot_bin="${GODOT_BIN:-$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64}"
apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
desktop_file="$apps_dir/virtual-anima-lab.desktop"

if [[ ! -x "$godot_bin" ]]; then
  printf 'Godot binary is missing or not executable: %s\n' "$godot_bin" >&2
  exit 2
fi
if [[ ! -f "$project_dir/project.godot" ]]; then
  printf 'Godot project.godot is missing: %s\n' "$project_dir" >&2
  exit 2
fi

# The desktop Exec value does not invoke a shell; reject characters whose
# escaping can alter the field-code/argument meaning. The standard local
# installation path is accepted.
if [[ ! "$godot_bin" =~ ^[a-zA-Z0-9_./-]+$ || ! "$project_dir" =~ ^[a-zA-Z0-9_./-]+$ ]]; then
  printf 'Launcher paths contain unsupported characters; use simple ASCII paths without spaces.\n' >&2
  exit 2
fi

mkdir -p -- "$apps_dir"

cat > "$desktop_file" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Virtual ANIMA Lab
GenericName=Standalone ANIMA virtual test world
Comment=Launch Virtual ANIMA Lab (F3 toggles diagnostics)
Exec=$godot_bin --path $project_dir -- --lab-port 46019 --lab-seed 7 --lab-scenario base --lab-ui normal
Path=$project_dir
Icon=applications-science
Terminal=false
Categories=Development;Education;
StartupNotify=true
Actions=Detour;Clutter;Debug;

[Desktop Action Detour]
Name=Detour (normal)
Exec=$godot_bin --path $project_dir -- --lab-port 46019 --lab-seed 7 --lab-scenario detour --lab-ui normal

[Desktop Action Clutter]
Name=Clutter (normal)
Exec=$godot_bin --path $project_dir -- --lab-port 46019 --lab-seed 7 --lab-scenario clutter --lab-ui normal

[Desktop Action Debug]
Name=Debug Mode (base)
Exec=$godot_bin --path $project_dir -- --lab-port 46019 --lab-seed 7 --lab-scenario base --lab-ui debug
EOF

chmod 644 "$desktop_file"
printf 'Installed launcher: %s\n' "$desktop_file"
printf 'Run: gtk-launch virtual-anima-lab\n'
printf 'In the window: F3 switches Normal / Debug without restarting Godot.\n'
printf 'Note: only one Lab instance may bind TCP port 46019.\n'

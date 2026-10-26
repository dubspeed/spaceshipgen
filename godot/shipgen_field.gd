## Builds a ShipGen asteroid field from its manifest (the "manifest" in <name>.json, written by
## cli.py --field or the panel's export): one breakable prefab rock per entry, placed and turned
## as listed. See docs/export_format.md, section "Asteroidenfelder".
##
##     var rocks := ShipGenField.build("res://fields/ore_belt_3.json", $Field)
##
## The prefab files (<name>_rock_<k>.glb) must lie next to the .json. Alternatively import
## <name>.glb itself: its Rock_<i> nodes carry a light preview mesh, a collider and extras
## "asteroid_instance" naming the prefab - swap the prefab in when the player comes close.
class_name ShipGenField
extends RefCounted


## Instance every rock of the manifest under [param parent]; returns the instances.
static func build(json_path: String, parent: Node3D) -> Array[Node3D]:
	var text := FileAccess.get_file_as_string(json_path)
	var data: Dictionary = JSON.parse_string(text)
	var manifest: Dictionary = data.get("manifest", data)
	var dir := json_path.get_base_dir()
	var scenes := {}
	var made: Array[Node3D] = []
	for rock in manifest["rocks"]:
		var file: String = rock["file"]
		if not scenes.has(file):
			scenes[file] = load(dir.path_join(file))
		var inst := (scenes[file] as PackedScene).instantiate() as Node3D
		inst.name = rock["name"]
		var p: Array = rock["position"]
		var q: Array = rock["rotation"]  # x, y, z, w (Godot axes)
		inst.transform = Transform3D(Basis(Quaternion(q[0], q[1], q[2], q[3])), Vector3(p[0], p[1], p[2]))
		inst.set_meta("shipgen_rock", rock)
		parent.add_child(inst)
		made.append(inst)
	return made

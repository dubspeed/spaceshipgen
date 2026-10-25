## Attaches your particle effects / lights to the FX anchors of an imported ShipGen scene
## (ship, wreck, station, asteroid). See docs/export_format.md, section "FX-Anker".
##
##     var effects := {
##         "exhaust": preload("res://fx/exhaust.tscn"),
##         "rcs": preload("res://fx/rcs_puff.tscn"),
##         "spark": preload("res://fx/sparks.tscn"),
##     }
##     ShipGenFx.attach($Ship, effects)
##
## An anchor's -Z axis points where the effect is emitted (set your ParticleProcessMaterial
## direction to (0, 0, -1)); its "size" scales the instance. Kinds without an entry are skipped.
class_name ShipGenFx
extends RefCounted

const KINDS := ["exhaust", "rcs", "mining", "nav_light", "spark", "smoke", "vent", "beacon",
		"berth_light", "sublimation"]

static var _name_re := RegEx.create_from_string("FX_(.+)_\\d+$")


## Every FX anchor below [param root]: [{node, kind, size, extras}].
static func anchors(root: Node) -> Array[Dictionary]:
	var out: Array[Dictionary] = []
	for node in root.find_children("*FX_*", "Node3D", true, false):
		var info := info_of(node)
		if not info.is_empty():
			out.append(info)
	return out


## Kind, size and the other extras of one anchor. Reads the glTF extras when the importer kept
## them as metadata ("extras"), otherwise falls back to the node name (FX_<kind>_<i>).
static func info_of(node: Node) -> Dictionary:
	var extras: Dictionary = node.get_meta("extras", {})
	if extras.has("shipgen_fx"):
		var fx: Dictionary = extras["shipgen_fx"]
		return {"node": node, "kind": fx.get("kind", ""), "size": float(fx.get("size", 1.0)), "extras": fx}
	var m := _name_re.search(node.name)
	if m == null or not KINDS.has(m.get_string(1)):
		return {}
	return {"node": node, "kind": m.get_string(1), "size": 1.0, "extras": {}}


## Instance effects[kind] under every matching anchor, scaled by its size; returns the instances.
static func attach(root: Node, effects: Dictionary, scale_by_size := true) -> Array[Node3D]:
	var made: Array[Node3D] = []
	for a in anchors(root):
		var scene: PackedScene = effects.get(a["kind"])
		if scene == null:
			continue
		var inst := scene.instantiate() as Node3D
		if scale_by_size:
			inst.scale = Vector3.ONE * a["size"]
		inst.set_meta("shipgen_fx", a["extras"])
		(a["node"] as Node).add_child(inst)
		made.append(inst)
	return made

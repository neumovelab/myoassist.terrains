import argparse
import json
import xml.etree.ElementTree as ET


def camera_xml_to_json(xml_string: str) -> dict[str, list[float]]:
    """
    Convert MuJoCo camera XML to JSON format matching ensemble config.

    Args:
        xml_string: XML string like '<camera pos="-1.151 -7.480 2.383" xyaxes="1.000 -0.009 0.000 0.004 0.387 0.922"/>'

    Returns:
        Dictionary with 'pos' and 'xyaxes' as lists of floats
    """
    # Parse the XML string
    root = ET.fromstring(xml_string)

    # Extract pos attribute and convert to list of floats
    pos_str = root.get("pos", "")
    pos = [float(x) for x in pos_str.split()] if pos_str else []

    # Extract xyaxes attribute and convert to list of floats
    xyaxes_str = root.get("xyaxes", "")
    xyaxes = [float(x) for x in xyaxes_str.split()] if xyaxes_str else []

    return {"pos": pos, "xyaxes": xyaxes}


def camera_json_to_xml(pos: list[float], xyaxes: list[float]) -> str:
    """Convert the ensemble-config form back to a MuJoCo <camera> element."""
    pos_s = " ".join(f"{v:.3f}" for v in pos)
    axes_s = " ".join(f"{v:.3f}" for v in xyaxes)
    return f'<camera pos="{pos_s}" xyaxes="{axes_s}"/>'


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a MuJoCo camera between XML and ensemble-config JSON.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--xml", help='a <camera .../> element, e.g. \'<camera pos="1 2 3" xyaxes="..."/>\'')
    group.add_argument("--json", help='{"pos": [...], "xyaxes": [...]}')
    args = parser.parse_args()
    if args.xml:
        print(json.dumps(camera_xml_to_json(args.xml), indent=2))
    else:
        payload = json.loads(args.json)
        print(camera_json_to_xml(payload["pos"], payload["xyaxes"]))


if __name__ == "__main__":
    main()

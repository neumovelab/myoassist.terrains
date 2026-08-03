import json
import xml.etree.ElementTree as ET
from typing import Dict, List


def camera_xml_to_json(xml_string: str) -> Dict[str, List[float]]:
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
    
    return {
        "pos": pos,
        "xyaxes": xyaxes
    }

# camera XML
camera_xml = '<camera pos="3.237 -0.079 1.209" xyaxes="0.016 1.000 0.000 -0.131 0.002 0.991"/>'

# Convert to JSON
camera_json = camera_xml_to_json(camera_xml)

# Pretty print the result
print(json.dumps(camera_json, indent=2))

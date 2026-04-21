module_name = "IrisTimelineExport"
module_description = (
    "Generates a DFIR-Report-style timeline diagram from marked case events "
    "and saves it to the case Datastore."
)
interface_version = "1.2.0"
module_version = "1.0.2"

pipeline_support = False
pipeline_info = {}

module_configuration = [
    {
        "param_name": "timeline_title_color",
        "param_human_name": "Title bar color (hex)",
        "param_description": "Hex color for the title bar, e.g. #AE0C0C",
        "default": "#AE0C0C",
        "mandatory": False,
        "type": "string",
        "section": "Rendering",
    },
]

module_name = "IrisTimelineExport"
module_description = (
    "Generates a DFIR-Report-style timeline diagram from marked case events "
    "and saves it to the case Datastore."
)
interface_version = "1.2.0"
module_version = "1.1.0"

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
    {
        "param_name": "timeline_highlight_color",
        "param_human_name": "Highlight border color (hex)",
        "param_description": "Hex color for the border of highlighted events, e.g. #FF8C00",
        "default": "#FF8C00",
        "mandatory": False,
        "type": "string",
        "section": "Rendering",
    },
    {
        "param_name": "timeline_category_colors",
        "param_human_name": "Category colors",
        "param_description": (
            "One entry per line: Category Name=#rrggbb. "
            "Lines starting with # are ignored."
        ),
        "default": "",
        "mandatory": False,
        "type": "textfield_plain",
        "section": "Rendering",
    },
]

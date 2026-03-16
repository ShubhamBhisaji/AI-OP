"""template_tool — Fill string templates with variable substitution."""
from __future__ import annotations
import json, re, logging
from string import Template

logger = logging.getLogger(__name__)


def template_tool(template: str, variables_json: str = "{}") -> str:
    """
    Render a string template by substituting named variables.

    template       : Template string using $variable or ${variable} syntax.
                     Example: "Hello $name, you have $count messages."
    variables_json : JSON object mapping variable names to values.
                     Example: '{"name": "Alice", "count": "3"}'

    Special actions (pass as template):
        list_vars  : Lists all $variables found in the template.
                     Usage: template_tool("list_vars", '{"tmpl": "Hello $name"}')

    Notes:
        • Use ${variable} for variables adjacent to other text (e.g. ${lang}script).
        • Missing variables will cause an error with the missing key name shown.
        • All variable values are coerced to strings.
    """
    if not isinstance(template, str):
        return "Error: 'template' must be a string."

    # Parse variables JSON
    if not variables_json or not variables_json.strip():
        variables_json = "{}"

    try:
        var_dict = json.loads(variables_json)
        if not isinstance(var_dict, dict):
            return "Error: 'variables_json' must be a JSON object ({...})."
    except json.JSONDecodeError as e:
        return f"Error parsing variables JSON: {e}"

    # Coerce all values to str
    var_dict = {str(k): str(v) for k, v in var_dict.items()}

    # Special action: list_vars
    if template.strip() == "list_vars":
        src = var_dict.get("tmpl", "")
        if not src:
            return "Error: Pass the template in variables_json as {\"tmpl\": \"...\"}."
        found = re.findall(r"\$(?:\{(\w+)\}|(\w+))", src)
        names = sorted({b or a for a, b in found})
        if not names:
            return "No variables found in template."
        return "Variables found:\n" + "\n".join(f"  ${n}" for n in names)

    # Render
    try:
        result = Template(template).substitute(var_dict)
    except KeyError as e:
        missing = str(e).strip("'\"")
        all_vars = re.findall(r"\$(?:\{(\w+)\}|(\w+))", template)
        required = sorted({b or a for a, b in all_vars})
        provided = sorted(var_dict.keys())
        return (
            f"Error: Missing variable ${missing}.\n"
            f"Required : {required}\n"
            f"Provided : {provided}"
        )
    except ValueError as e:
        return f"Error in template syntax: {e}"

    return result

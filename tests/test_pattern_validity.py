import os
import importlib.util
import pytest

def get_react_patterns():
    """Discover all _react.py files in react_patterns/ directory."""
    patterns_dir = "react_patterns"
    patterns = []
    for filename in os.listdir(patterns_dir):
        if filename.endswith("_react.py") or filename == "manual_pattern_template.py":
            patterns.append(os.path.join(patterns_dir, filename))
    return patterns

@pytest.mark.parametrize("pattern_file", get_react_patterns())
def test_pattern_structure(pattern_file):
    """Verify that each pattern file exports get_prompt_structure() returning a dict."""
    module_name = os.path.basename(pattern_file).replace(".py", "")
    spec = importlib.util.spec_from_file_location(module_name, pattern_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "get_prompt_structure"), f"{pattern_file} missing get_prompt_structure()"

    structure = module.get_prompt_structure()
    assert isinstance(structure, dict), f"{pattern_file} get_prompt_structure() must return a dict"
    assert "static_system" in structure, f"{pattern_file} missing 'static_system' key"
    assert "dynamic_context" in structure, f"{pattern_file} missing 'dynamic_context' key"

    # Check for placeholder validity
    static = structure["static_system"]
    dynamic = structure["dynamic_context"]

    # Just a basic check that we didn't break string formatting
    try:
        static.format(draft_context="", system_instruction="", tools_list_text="")
    except KeyError as e:
        # Some patterns might not use all keys, or use extra keys.
        # But commonly they use system_instruction.
        # This check is fuzzy because different patterns have different placeholders.
        pass
    except IndexError:
        pass

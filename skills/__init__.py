import ast
import importlib
from functools import lru_cache
from pathlib import Path


def _is_baseskill_class(class_def: ast.ClassDef) -> bool:
    """Check whether this class directly inherits BaseSkill."""
    for base in class_def.bases:
        if isinstance(base, ast.Name) and base.id == "BaseSkill":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseSkill":
            return True
        if isinstance(base, ast.Subscript):
            base_value = base.value
            if isinstance(base_value, ast.Name) and base_value.id == "BaseSkill":
                return True
            if isinstance(base_value, ast.Attribute) and base_value.attr == "BaseSkill":
                return True
    return False


def _extract_value(value_node: ast.AST):
    """Extract simple constant values from AST nodes."""
    if isinstance(value_node, ast.Constant):
        return value_node.value
    if isinstance(value_node, ast.Name):
        return f"<{value_node.id}>"
    if isinstance(value_node, ast.Attribute):
        return f"{_extract_value(value_node.value)}.{value_node.attr}"
    return f"<{ast.unparse(value_node)}>"


def _extract_name_from_init(class_node: ast.ClassDef):
    """
    Extract skill name from __init__ method.
    Supports:
    1. self.name = "xxx"
    2. super().__init__("xxx", ...)
    """
    for node in class_node.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "__init__":
            continue

        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and target.attr == "name"
                    ):
                        return _extract_value(stmt.value)

            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "__init__"
                    and isinstance(call.func.value, ast.Call)
                    and isinstance(call.func.value.func, ast.Name)
                    and call.func.value.func.id == "super"
                    and call.args
                ):
                    return _extract_value(call.args[0])

    return None


@lru_cache(maxsize=1)
def _collect_skill_registry() -> dict[str, tuple[str, str]]:
    """
    Build registry: {skill_name: (module_path, class_name)}
    """
    skills_dir = Path(__file__).parent
    discovered: dict[str, list[tuple[str, str]]] = {}

    for py_file in sorted(skills_dir.glob("*.py")):
        if py_file.name in {"__init__.py", "base.py"}:
            continue

        with py_file.open("r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(py_file))

        module_path = f"{__name__}.{py_file.stem}"

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not _is_baseskill_class(node):
                continue

            skill_name = _extract_name_from_init(node)
            if not isinstance(skill_name, str) or not skill_name:
                continue

            discovered.setdefault(skill_name, []).append((module_path, node.name))

    registry: dict[str, tuple[str, str]] = {}
    for skill_name, candidates in discovered.items():
        if len(candidates) == 1:
            registry[skill_name] = candidates[0]
            continue

        exact_module_match = [
            candidate
            for candidate in candidates
            if candidate[0].split(".")[-1] == skill_name
        ]
        if len(exact_module_match) == 1:
            registry[skill_name] = exact_module_match[0]
            continue

        raise ValueError(
            f"Duplicate skill name '{skill_name}' found in modules: "
            + ", ".join(module for module, _ in candidates)
        )

    return registry


def get_available_skills() -> list[str]:
    """Return all discovered/available skill names."""
    return sorted(_collect_skill_registry().keys())


def import_skill(skill_name: str):
    """
    Return Skill class by skill name.

    Example:
        module = importlib.import_module(module_path)
        Skill = getattr(module, class_name)
    """
    registry = _collect_skill_registry()
    if skill_name not in registry:
        raise KeyError(f"Unknown skill name: {skill_name}")

    module_path, class_name = registry[skill_name]
    module = importlib.import_module(module_path)
    Skill = getattr(module, class_name)
    return Skill


def execute_skill(
    skill_name: str,
    client,
    conversation_id: str,
    conversation_short_id: int | str,
    config_raw,
    is_group: bool = False,
):
    Skill = import_skill(skill_name)
    skill = Skill(client)
    config = skill.build_config(config_raw)
    return skill.execute(
        conversation_id=conversation_id,
        conversation_short_id=conversation_short_id,
        is_group=is_group,
        config=config,
    )


__all__ = ["get_available_skills", "import_skill", "execute_skill"]

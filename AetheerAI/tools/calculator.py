"""calculator — Safe math expression evaluator."""
from __future__ import annotations
import ast, math, logging

logger = logging.getLogger(__name__)

_SAFE_NAMES = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
_SAFE_NAMES.update({"abs": abs, "round": round, "min": min, "max": max,
                    "sum": sum, "pow": pow, "int": int, "float": float})

class _SafeVisitor(ast.NodeVisitor):
    _ALLOWED = {
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Constant,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv,
        ast.USub, ast.UAdd, ast.Name, ast.Load,
    }
    def generic_visit(self, node):
        if type(node) not in self._ALLOWED:
            raise ValueError(f"Unsafe expression: {type(node).__name__}")
        return super().generic_visit(node)

def calculator(expression: str) -> str:
    """
    Evaluate a safe math expression and return the result.
    Supports: +, -, *, /, **, %, //, and all math module functions.
    """
    if not expression or not isinstance(expression, str):
        return "Error: expression must be a non-empty string."
    expr = expression.strip()
    try:
        tree = ast.parse(expr, mode="eval")
        _SafeVisitor().visit(tree)
        result = eval(compile(tree, "<expression>", "eval"), {"__builtins__": {}}, _SAFE_NAMES)
        logger.info("calculator: %s = %s", expr, result)
        return str(result)
    except ZeroDivisionError:
        return "Error: division by zero."
    except Exception as exc:
        return f"Error evaluating expression: {exc}"

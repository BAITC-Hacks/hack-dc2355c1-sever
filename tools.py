"""Инструменты агента.

Чтобы добавить свой: напишите функцию, повесьте @tool с описанием
параметров — схема для API соберётся сама.
"""

import ast
import datetime
import inspect
import json
import operator

REGISTRY = {}
SCHEMAS = []

_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def tool(description, **param_docs):
    """Декоратор: превращает функцию в инструмент для модели."""
    def wrapper(func):
        signature = inspect.signature(func)
        properties, required = {}, []
        for name, param in signature.parameters.items():
            json_type = _TYPES.get(param.annotation, "string")
            properties[name] = {"type": json_type,
                                "description": param_docs.get(name, name)}
            if param.default is inspect.Parameter.empty:
                required.append(name)

        SCHEMAS.append({
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": description,
                "parameters": {"type": "object", "properties": properties,
                               "required": required},
            },
        })
        REGISTRY[func.__name__] = func
        return func
    return wrapper


def run(name, arguments_json):
    """Выполнить инструмент по имени. Ошибку возвращаем модели текстом,
    чтобы она могла исправиться, а не падаем."""
    func = REGISTRY.get(name)
    if func is None:
        return "Ошибка: инструмента {} не существует.".format(name)
    try:
        arguments = json.loads(arguments_json or "{}")
        return str(func(**arguments))
    except Exception as error:
        return "Ошибка при вызове {}: {}".format(name, error)


# ---------------------------------------------------------------- примеры

@tool("Текущие дата и время по Астане.")
def current_time():
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5)))
    return now.strftime("%Y-%m-%d %H:%M (GMT+5)")


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.Mod: operator.mod}


def _eval_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp):
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        return _OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("недопустимое выражение")


@tool("Посчитать арифметическое выражение, например '1250 * 0.12'.",
      expression="выражение на Python-синтаксисе, только числа и + - * / ** %")
def calculate(expression: str):
    return _eval_node(ast.parse(expression, mode="eval").body)

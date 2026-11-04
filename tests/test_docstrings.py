"""Every public name carries a docstring, and every callable carries an example."""

import dataclasses
import inspect

import flowsim


def _own_members(cls):
    """Public members defined by ``cls`` or its FlowSim bases, not by ``object``."""
    generated = set()
    if dataclasses.is_dataclass(cls):
        generated = {"__init__", "__repr__", "__eq__"}
    for name, member in inspect.getmembers(cls):
        if name.startswith("_") or name in generated:
            continue
        if hasattr(object, name):
            continue
        if not (inspect.isroutine(member) or isinstance(member, property)):
            continue
        yield name, member


def _check(label, obj, needs_example, problems):
    doc = inspect.getdoc(obj)
    if not doc:
        problems.append(f"{label}: missing docstring")
    elif needs_example and "Example" not in doc:
        problems.append(f"{label}: docstring has no Example section")


def test_public_names_are_documented():
    problems = []
    for name in flowsim.__all__:
        obj = getattr(flowsim, name)
        if inspect.isclass(obj):
            _check(name, obj, False, problems)
            for member_name, member in _own_members(obj):
                is_property = isinstance(member, property)
                _check(f"{name}.{member_name}", member, not is_property, problems)
        elif inspect.isroutine(obj):
            _check(name, obj, True, problems)
    assert not problems, "\n".join(problems)

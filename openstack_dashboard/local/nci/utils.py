# openstack_dashboard.local.nci.utils
#
# Copyright (c) 2014, NCI, Australian National University.
# All Rights Reserved.
#


def subclass_meta_type(base_class):
    """Returns a "Meta" type using the given base class.

    This is required because "horizon.workflows.base.ActionMetaclass" removes
    "Meta" from the class namespace during initialisation which in turn means
    that it can't be referenced in a subclass since it no longer exists.
    Instead, we copy all the attributes from the base class which includes
    those assigned from the original "Meta" class by "ActionMetaclass".
    """
    return type("Meta",
        (object,),
        dict(filter(lambda x: not x[0].startswith("_"), vars(base_class).iteritems())))


def undecorate(func, name):
    """Returns original undecorated version of a given function."""
    if hasattr(func, "__closure__") and func.__closure__:
        for cell in func.__closure__:
            if cell.cell_contents is not func:
                rv = undecorate(cell.cell_contents, name)
                if rv:
                    return rv

    if hasattr(func, "__code__") and hasattr(func, "__name__") and (func.__name__ == name):
        return func
    else:
        return None


class AttributeProxy(object):
    """Wraps a Python object allowing local modifications to the attribute
    namespace."""

    def __init__(self, obj):
        self.__wrapped = obj

    def __getattr__(self, name):
        return getattr(self.__wrapped, name)


# vim:ts=4 et sw=4 sts=4:

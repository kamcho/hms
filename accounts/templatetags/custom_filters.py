from django import template

register = template.Library()

@register.filter(name='format_number')
def format_number(value, decimal_places=2):
    """
    Format a number with commas as thousand separators and optional decimal places
    """
    if value is None:
        return "0"
    try:
        num = float(value)
        if num.is_integer():
            return "{:,}".format(int(num))
        return "{0:,.{1}f}".format(num, decimal_places)
    except (ValueError, TypeError):
        return value

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.filter(name='subtract')
def subtract(value, arg):
    """
    Subtract the arg from the value
    """
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return value

@register.filter(name='multiply')
def multiply(value, arg):
    """
    Multiply the value by the arg
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0
@register.filter(name='abs')
def absolute_value(value):
    """
    Return the absolute value of the input
    """
    try:
        return abs(float(value))
    except (ValueError, TypeError):
        return value

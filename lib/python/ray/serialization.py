import numpy as np
import pickling
import libraylib as raylib
import libnumbuf

def is_argument_serializable(value):
  """Checks if value is a composition of primitive types.

  This will return True if the argument is one of the following:
    - An int
    - A float
    - A bool
    - None
    - A list of length at most 100 whose elements are serializable
    - A tuple of length at most 100 whose elements are serializable
    - A dict of length at most 100 whose keys and values are serializable
    - A string of length at most 100.
    - A unicode string of length at most 100.

  Args:
    value: A Python object.

  Returns:
    True if the object can be serialized as a composition of primitive types and
      False otherwise.
  """
  t = type(value)
  if t is int or t is float or t is long or t is bool or value is None:
    return True
  if t is list:
    if len(value) <= 100:
      for element in value:
        if not is_argument_serializable(element):
          return False
      return True
    else:
      return False
  if t is tuple:
    if len(value) <= 100:
      for element in value:
        if not is_argument_serializable(element):
          return False
      return True
    else:
      return False
  if t is dict:
    if len(value) <= 100:
      for k, v in value.iteritems():
        if not is_argument_serializable(k) or not is_argument_serializable(v):
          return False
      return True
    else:
      return False
  if t is str:
    return len(value) <= 100
  if t is unicode:
    return len(value) <= 100
  return False

def serialize_argument_if_possible(value):
  """This method serializes arguments that are passed by value.

  The result will be deserialized by deserialize_argument.

  Returns:
    None if value cannot be efficiently serialized or is too big, and otherwise
      this returns the serialized value as a string.
  """
  if not is_argument_serializable(value):
    # The argument is not obviously serializable using __repr__, so we will not
    # serialize it.
    return None
  serialized_value = value.__repr__()
  if len(serialized_value) > 1000:
    # The argument is too big, so we will not pass it by value.
    return None
  # Return the serialized argument.
  return serialized_value

def deserialize_argument(serialized_value):
  """This method deserializes arguments that are passed by value.

  The argument will have been serialized by serialize_argument.
  """
  return eval(serialized_value)

def check_serializable(cls):
  """Throws an exception if Ray cannot serialize this class efficiently.

  Args:
    cls (type): The class to be serialized.

  Raises:
    Exception: An exception is raised if Ray cannot serialize this class
      efficiently.
  """
  if is_named_tuple(cls):
    # This case works.
    return
  if not hasattr(cls, "__new__"):
    raise Exception("The class {} does not have a '__new__' attribute, and is probably an old-style class. We do not support this. Please either make it a new-style class by inheriting from 'object', or use 'ray.register_class(cls, pickle=True)'. However, note that pickle is inefficient.".format(cls))
  try:
    obj = cls.__new__(cls)
  except:
    raise Exception("The class {} has overridden '__new__', so Ray may not be able to serialize it efficiently. Try using 'ray.register_class(cls, pickle=True)'. However, note that pickle is inefficient.".format(cls))
  if not hasattr(obj, "__dict__"):
    raise Exception("Objects of the class {} do not have a `__dict__` attribute, so Ray cannot serialize it efficiently. Try using 'ray.register_class(cls, pickle=True)'. However, note that pickle is inefficient.".format(cls))
  if hasattr(obj, "__slots__"):
    raise Exception("The class {} uses '__slots__', so Ray may not be able to serialize it efficiently. Try using 'ray.register_class(cls, pickle=True)'. However, note that pickle is inefficient.".format(cls))

# This field keeps track of a whitelisted set of classes that Ray will
# serialize.
whitelisted_classes = {}
classes_to_pickle = set()
custom_serializers = {}
custom_deserializers = {}

def class_identifier(typ):
  """Return a string that identifies this type."""
  return "{}.{}".format(typ.__module__, typ.__name__)

def is_named_tuple(cls):
  """Return True if cls is a namedtuple and False otherwise."""
  b = cls.__bases__
  if len(b) != 1 or b[0] != tuple:
    return False
  f = getattr(cls, "_fields", None)
  if not isinstance(f, tuple):
    return False
  return all(type(n) == str for n in f)

def add_class_to_whitelist(cls, pickle=False, custom_serializer=None, custom_deserializer=None):
  """Add cls to the list of classes that we can serialize.

  Args:
    cls (type): The class that we can serialize.
    pickle (bool): True if the serialization should be done with pickle. False
      if it should be done efficiently with Ray.
    custom_serializer: This argument is optional, but can be provided to
      serialize objects of the class in a particular way.
    custom_deserializer: This argument is optional, but can be provided to
      deserialize objects of the class in a particular way.
  """
  class_id = class_identifier(cls)
  whitelisted_classes[class_id] = cls
  if pickle:
    classes_to_pickle.add(class_id)
  if custom_serializer is not None:
    custom_serializers[class_id] = custom_serializer
    custom_deserializers[class_id] = custom_deserializer

# Here we define a custom serializer and deserializer for handling numpy
# arrays that contain objects.
def array_custom_serializer(obj):
  return obj.tolist(), obj.dtype.str
def array_custom_deserializer(serialized_obj):
  return np.array(serialized_obj[0], dtype=np.dtype(serialized_obj[1]))
add_class_to_whitelist(np.ndarray, pickle=False, custom_serializer=array_custom_serializer, custom_deserializer=array_custom_deserializer)

def serialize(obj):
  """This is the callback that will be used by numbuf.

  If numbuf does not know how to serialize an object, it will call this method.

  Args:
    obj (object): A Python object.

  Returns:
    A dictionary that has the key "_pyttype_" to identify the class, and
      contains all information needed to reconstruct the object.
  """
  class_id = class_identifier(type(obj))
  if class_id not in whitelisted_classes:
    raise Exception("Ray does not know how to serialize the object {}. To fix this, call 'ray.register_class' on the class of the object.".format(obj))
  if class_id in classes_to_pickle:
    serialized_obj = {"data": pickling.dumps(obj)}
  elif class_id in custom_serializers.keys():
    serialized_obj = {"data": custom_serializers[class_id](obj)}
  else:
    if not hasattr(obj, "__dict__"):
      raise Exception("We do not know how to serialize the object '{}'".format(obj))
    serialized_obj = obj.__dict__
    if is_named_tuple(type(obj)):
      # Handle the namedtuple case.
      serialized_obj["_ray_getnewargs_"] = obj.__getnewargs__()
  result = dict(serialized_obj, **{"_pytype_": class_id})
  return result

def deserialize(serialized_obj):
  """This is the callback that will be used by numbuf.

  If numbuf encounters a dictionary that contains the key "_pytype_" during
    deserialization, it will ask this callback to deserialize the object.

  Args:
    serialized_obj (object): A dictionary that contains the key "_pytype_".

  Returns:
    A Python object.
  """
  class_id = serialized_obj["_pytype_"]
  cls = whitelisted_classes[class_id]
  if class_id in classes_to_pickle:
    obj = pickling.loads(serialized_obj["data"])
  elif class_id in custom_deserializers.keys():
    obj = custom_deserializers[class_id](serialized_obj["data"])
  else:
    # In this case, serialized_obj should just be the __dict__ field.
    if "_ray_getnewargs_" in serialized_obj:
      obj = cls.__new__(cls, *serialized_obj["_ray_getnewargs_"])
      serialized_obj.pop("_ray_getnewargs_")
    else:
      obj = cls.__new__(cls)
    serialized_obj.pop("_pytype_")
    obj.__dict__.update(serialized_obj)
  return obj

# Register the callbacks with numbuf.
libnumbuf.register_callbacks(serialize, deserialize)

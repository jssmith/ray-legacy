from types import ModuleType
import time
import typing
import numpy as np
import pynumbuf
import scipy.sparse as sp

import orchpy
import serialization

class Worker(object):
  """The methods in this class are considered unexposed to the user. The functions outside of this class are considered exposed."""

  def __init__(self):
    self.functions = {}
    self.handle = None

  def put_object(self, objref, value):
    """Put `value` in the local object store with objref `objref`. This assumes that the value for `objref` has not yet been placed in the local object store."""
    if type(value) == sp.csr_matrix:
      d = {"shape": np.array(value.shape), "data": value.data, "indices": value.indices, "indptr": value.indptr}
      orchpy.lib.put_arrow(self.handle, objref, d)
    elif type(value) == np.ndarray:
      orchpy.lib.put_arrow(self.handle, objref, value)
    elif type(value) == sp.coo_matrix:
      d = {"shape": np.array(value.shape), "row": value.row, "col": value.col, "data": value.data}
      orchpy.lib.put_arrow(self.handle, objref, d)
    elif type(value) == dict or type(value) == np.ndarray:
      orchpy.lib.put_arrow(value)
    else:
      object_capsule, contained_objrefs = serialization.serialize(self.handle, value) # contained_objrefs is a list of the objrefs contained in object_capsule
      orchpy.lib.put_object(self.handle, objref, object_capsule, contained_objrefs)

  def get_object(self, objref):
    """
    Return the value from the local object store for objref `objref`. This will
    block until the value for `objref` has been written to the local object store.

    WARNING: get_object can only be called on a canonical objref.
    """
    if orchpy.lib.is_arrow(self.handle, objref):
      d = orchpy.lib.get_arrow(self.handle, objref)
      if type(d) == dict and len(d) == 4:
        if all (k in d for k in ("shape", "data", "indices", "indptr")):
          return sp.csr_matrix((d["data"], d["indices"], d["indptr"]), shape=d["shape"])
        elif all (k in d for k in ("shape", "row", "col", "data")):
          return sp.coo_matrix((d["data"], (d["row"], d["col"])), shape=d["shape"])
      return d
    else:
      object_capsule = orchpy.lib.get_object(self.handle, objref)
      return serialization.deserialize(self.handle, object_capsule)

  def alias_objrefs(self, alias_objref, target_objref):
    """Make `alias_objref` refer to the same object that `target_objref` refers to."""
    orchpy.lib.alias_objrefs(self.handle, alias_objref, target_objref)

  def register_function(self, function):
    """Notify the scheduler that this worker can execute the function with name `func_name`. Store the function `function` locally."""
    orchpy.lib.register_function(self.handle, function.func_name, len(function.return_types))
    self.functions[function.func_name] = function

  def remote_call(self, func_name, args):
    """Tell the scheduler to schedule the execution of the function with name `func_name` with arguments `args`. Retrieve object references for the outputs of the function from the scheduler and immediately return them."""
    call_capsule = serialization.serialize_call(self.handle, func_name, args)
    objrefs = orchpy.lib.remote_call(self.handle, call_capsule)
    return objrefs

# We make `global_worker` a global variable so that there is one worker per worker process.
global_worker = Worker()

def scheduler_info(worker=global_worker):
  return orchpy.lib.scheduler_info(worker.handle);

def register_module(module, recursive=False, worker=global_worker):
  print "registering functions in module {}.".format(module.__name__)
  for name in dir(module):
    val = getattr(module, name)
    if hasattr(val, "is_distributed") and val.is_distributed:
      print "registering {}.".format(val.func_name)
      worker.register_function(val)
    # elif recursive and isinstance(val, ModuleType):
    #   register_module(val, recursive, worker)

def connect(scheduler_addr, objstore_addr, worker_addr, worker=global_worker):
  if hasattr(worker, "handle"):
    del worker.handle
  worker.handle = orchpy.lib.create_worker(scheduler_addr, objstore_addr, worker_addr)

def disconnect(worker=global_worker):
  orchpy.lib.disconnect(worker.handle)

def pull(objref, worker=global_worker):
  orchpy.lib.request_object(worker.handle, objref)
  return worker.get_object(objref)

def push(value, worker=global_worker):
  objref = orchpy.lib.get_objref(worker.handle)
  worker.put_object(objref, value)
  return objref

def main_loop(worker=global_worker):
  if not orchpy.lib.connected(worker.handle):
    raise Exception("Worker is attempting to enter main_loop but has not been connected yet.")
  orchpy.lib.start_worker_service(worker.handle)
  def process_call(call): # wrapping these calls in a function should cause the local variables to go out of scope more quickly, which is useful for inspecting reference counts
    a = time.time()
    func_name, args, return_objrefs = serialization.deserialize_call(worker.handle, call)
    b = time.time() - a
    print "deserialize took ", b
    a = time.time()
    arguments = get_arguments_for_execution(worker.functions[func_name], args, worker) # get args from objstore
    b = time.time() - a
    print "getting args took ", b
    a = time.time()
    outputs = worker.functions[func_name].executor(arguments) # execute the function
    b = time.time() - a
    print "executing took ", b
    a = time.time()
    store_outputs_in_objstore(return_objrefs, outputs, worker) # store output in local object store
    orchpy.lib.notify_task_completed(worker.handle) # notify the scheduler that the task has completed
    a = time.time() - a
    print "finishing took ", a
  while True:
    call = orchpy.lib.wait_for_next_task(worker.handle)
    process_call(call)

def distributed(arg_types, return_types, worker=global_worker):
  def distributed_decorator(func):
    def func_executor(arguments):
      """This is what gets executed remotely on a worker after a distributed function is scheduled by the scheduler."""
      # print "Calling function {}".format(func.__name__)
      result = func(*arguments)
      check_return_values(func_call, result) # throws an exception if result is invalid
      # print "Finished executing function {}".format(func.__name__)
      return result
    def func_call(*args):
      """This is what gets run immediately when a worker calls a distributed function."""
      check_arguments(func_call, list(args)) # throws an exception if args are invalid
      objrefs = worker.remote_call(func_call.func_name, list(args))
      return objrefs[0] if len(objrefs) == 1 else objrefs
    func_call.func_name = "{}.{}".format(func.__module__, func.__name__)
    func_call.executor = func_executor
    func_call.arg_types = arg_types
    func_call.return_types = return_types
    func_call.is_distributed = True
    return func_call
  return distributed_decorator

# helper method, this should not be called by the user
def check_return_values(function, result):
  if len(function.return_types) == 1:
    result = (result,)
    # if not isinstance(result, function.return_types[0]):
    #   raise Exception("The @distributed decorator for function {} expects one return value with type {}, but {} returned a {}.".format(function.__name__, function.return_types[0], function.__name__, type(result)))
  else:
    if len(result) != len(function.return_types):
      raise Exception("The @distributed decorator for function {} has {} return values with types {}, but {} returned {} values.".format(function.__name__, len(function.return_types), function.return_types, function.__name__, len(result)))
    for i in range(len(result)):
      if (not isinstance(result[i], function.return_types[i])) and (not isinstance(result[i], orchpy.lib.ObjRef)):
        raise Exception("The {}th return value for function {} has type {}, but the @distributed decorator expected a return value of type {} or an ObjRef.".format(i, function.__name__, type(result[i]), function.return_types[i]))

# helper method, this should not be called by the user
def check_arguments(function, args):
  # check the number of args
  if len(args) != len(function.arg_types) and function.arg_types[-1] is not None:
    raise Exception("Function {} expects {} arguments, but received {}.".format(function.__name__, len(function.arg_types), len(args)))
  elif len(args) < len(function.arg_types) - 1 and function.arg_types[-1] is None:
    raise Exception("Function {} expects at least {} arguments, but received {}.".format(function.__name__, len(function.arg_types) - 1, len(args)))

  for (i, arg) in enumerate(args):
    if i < len(function.arg_types) - 1:
      expected_type = function.arg_types[i]
    elif i == len(function.arg_types) - 1 and function.arg_types[-1] is not None:
      expected_type = function.arg_types[-1]
    elif function.arg_types[-1] is None and len(function.arg_types) > 1:
      expected_type = function.arg_types[-2]
    else:
      assert False, "This code should be unreachable."

    if isinstance(arg, orchpy.lib.ObjRef):
      # TODO(rkn): When we have type information in the ObjRef, do type checking here.
      pass
    else:
      if not isinstance(arg, expected_type): # TODO(rkn): This check doesn't really work, e.g., isinstance([1,2,3], typing.List[str]) == True
        raise Exception("Argument {} for function {} has type {} but an argument of type {} was expected.".format(i, function.__name__, type(arg), expected_type))

# helper method, this should not be called by the user
def get_arguments_for_execution(function, args, worker=global_worker):
  # TODO(rkn): Eventually, all of the type checking can be put in `check_arguments` above so that the error will happen immediately when calling a remote function.
  arguments = []
  """
  # check the number of args
  if len(args) != len(function.arg_types) and function.arg_types[-1] is not None:
    raise Exception("Function {} expects {} arguments, but received {}.".format(function.__name__, len(function.arg_types), len(args)))
  elif len(args) < len(function.arg_types) - 1 and function.arg_types[-1] is None:
    raise Exception("Function {} expects at least {} arguments, but received {}.".format(function.__name__, len(function.arg_types) - 1, len(args)))
  """

  for (i, arg) in enumerate(args):
    if i < len(function.arg_types) - 1:
      expected_type = function.arg_types[i]
    elif i == len(function.arg_types) - 1 and function.arg_types[-1] is not None:
      expected_type = function.arg_types[-1]
    elif function.arg_types[-1] is None and len(function.arg_types) > 1:
      expected_type = function.arg_types[-2]
    else:
      assert False, "This code should be unreachable."

    if isinstance(arg, orchpy.lib.ObjRef):
      # get the object from the local object store
      # print "Getting argument {} for function {}.".format(i, function.__name__)
      argument = worker.get_object(arg)
      # print "Successfully retrieved argument {} for function {}.".format(i, function.__name__)
    else:
      # pass the argument by value
      argument = arg

    if not isinstance(argument, expected_type):
      raise Exception("Argument {} for function {} has type {} but an argument of type {} was expected.".format(i, function.__name__, type(argument), expected_type))
    arguments.append(argument)
  return arguments

# helper method, this should not be called by the user
def store_outputs_in_objstore(objrefs, outputs, worker=global_worker):
  if len(objrefs) == 1:
    outputs = (outputs,)

  for i in range(len(objrefs)):
    if isinstance(outputs[i], orchpy.lib.ObjRef):
      # An ObjRef is being returned, so we must alias objrefs[i] so that it refers to the same object that outputs[i] refers to
      print "Aliasing objrefs {} and {}".format(objrefs[i].val, outputs[i].val)
      worker.alias_objrefs(objrefs[i], outputs[i])
      pass
    else:
      worker.put_object(objrefs[i], outputs[i])

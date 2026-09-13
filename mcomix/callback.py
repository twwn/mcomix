import traceback
import weakref
import threading
from gi.repository import GLib

from mcomix import log
from mcomix.i18n import _

from collections.abc import Callable
from typing import Concatenate


class CallbackList[T, **P, R]:
    """ Helper class for implementing callbacks within the main thread.
    Add listeners to method calls with method += callback_function. """

    def __init__(self, obj: T,
                 function: Callable[Concatenate[T, P], R]) -> None:
        self.__callbacks: "list[tuple[weakref.ref[object] | None, Callable[..., object]]]" = []  # type: ignore[explicit-any]  # a listener takes what the call it listens to takes
        self.__object = obj
        self.__function = function

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R | None:
        """ Runs the wrapped function. After the funtion has finished,
        callbacks are run. Code within the function and the callback is
        always executed in the main thread. """

        if threading.current_thread() is threading.main_thread():
            result = self.__function(self.__object, *args, **kwargs)
            self.__run_callbacks(*args, **kwargs)
            return result
        else:
            # Call this method again in the main thread.  Nothing waits
            # on the answer in that case, so there is none to give.
            def in_main_thread() -> bool:
                self(*args, **kwargs)
                # Remove this function from the idle queue.  This was a
                # bare 0, which GLib reads the same way, but the name
                # says which of the two answers an idle source can give
                # is meant.
                return GLib.SOURCE_REMOVE

            GLib.idle_add(in_main_thread)
            return None

    def __iadd__(self, function: Callable[..., object]) -> "CallbackList[T, P, R]":  # type: ignore[explicit-any]  # a listener takes what the call it listens to takes
        """ Support for 'method += callback_function' syntax. """
        obj, func = self.__get_function(function)

        if (obj, func) not in self.__callbacks:
            self.__callbacks.append((obj, func))

        return self

    def __isub__(self, function: Callable[..., object]) -> "CallbackList[T, P, R]":  # type: ignore[explicit-any]  # a listener takes what the call it listens to takes
        """ Support for 'method -= callback_function' syntax. """
        obj, func = self.__get_function(function)

        if (obj, func) in self.__callbacks:
            self.__callbacks.remove((obj, func))

        return self

    def __run_callbacks(self, *args: P.args, **kwargs: P.kwargs) -> None:
        """ Executes callback functions. """
        for obj_ref, func in self.__callbacks:

            callback: "Callable[..., object] | None"  # type: ignore[explicit-any]  # a listener takes what the call it listens to takes
            if obj_ref is None:
                # Callback is a normal function
                callback = func
            else:
                # Callback is a bound method. Recreate it by binding the
                # function to the object, unless that no longer exists.
                obj = obj_ref()
                callback = None if obj is None else func.__get__(obj)

            if callback is not None:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    log.error(_('! Callback %(function)r failed: %(error)s'),
                              {'function': callback, 'error': e})
                    log.debug('Traceback:\n%s', traceback.format_exc())

    def __callback_deleted(self, obj_ref: "weakref.ref[object]") -> None:
        """ Called whenever one of the callback objects is collected by gc.
        This removes all callback functions registered by the object. """
        self.__callbacks = [callback for callback in self.__callbacks if callback[0] != obj_ref]

    def __get_function(  # type: ignore[explicit-any]  # a listener takes what the call it listens to takes
            self,
            func: Callable[..., object],
    ) -> "tuple[weakref.ref[object] | None, Callable[..., object]]":
        """ If <func> is a normal function, return (None, func).
        If <func> is a bound method, return (weakref(obj), func), with <obj>
        being the object <func> is bound to. This is required since
        weak references do not work on bound methods. """

        obj = getattr(func, '__self__', None)
        if obj is not None:
            # Keep the plain function beside a weak reference to the
            # object: a weak reference to the bound method itself would
            # be dead as soon as it was made, since nothing else holds
            # one.
            return (weakref.ref(obj, self.__callback_deleted),
                    getattr(func, '__func__', func))
        else:
            return (None, func)


class Callback[T, **P, R]:
    """ Decorator class for using the CallbackList helper. """

    def __init__(self, function: Callable[Concatenate[T, P], R]) -> None:
        # This is the function the Callback is decorating.
        self.__function = function

    def __get__(self, obj: T, cls: "type[T] | None" = None) -> "CallbackList[T, P, R]":
        """ This method makes Callback implement the descriptor interface.
        Enables calling bound methods with the correct <self> reference.
        Do not ask me why or how this actually works, I simply do not know. """

        return CallbackList(obj, self.__function)

# vim: expandtab:sw=4:ts=4

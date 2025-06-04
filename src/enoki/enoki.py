#!/usr/bin/env python3
"""
Enoki provides a framework for creating and managing finite state machines (FSMs).
It includes classes for defining states, transitions, and managing shared state between
different states. The library supports features such as state retries, timeouts,
pushdown automata (state stack), and error handling.

Key Components:
- `State`: Base class for defining states. Users can extend this class to create custom states.
- `StateMachine`: Manages state transitions, shared state, and message queues.
- `SharedState`: Facilitates sharing information between states and the FSM.
- `TransitionType`: Base class for defining transition types (e.g., Push, Pop, Repeat, Retry).
- `DefaultStates`: Contains default states like `End`.
- `GenericCommon`: A container for shared state when no custom shared state is provided.

Features:
1. State Lifecycle:
    - `on_enter`: Called when entering a state.
    - `on_leave`: Called when leaving a state.
    - `on_state`: Main handler for state logic (required for all states).
    - `on_fail`: Called when a state exceeds its retry limit.
    - `on_timeout`: Called when a state exceeds its timeout duration.

2. Transition Types:
    - `Push`: Pushes states onto a stack and transitions to the first state.
    - `Pop`: Pops the top state off the stack and transitions to it.
    - `Repeat`: Re-enters the same state from the beginning.
    - `Retry`: Restarts the current state without transitioning.

3. Error Handling:
    - Custom exceptions for various error conditions (e.g., `StateRetryLimitError`, `StateTimedOut`).
    - Default error state for handling unhandled exceptions.

4. Timeout and Retry:
    - States can define `TIMEOUT` and `RETRIES` class variables for automatic timeout and retry handling.

5. Non-blocking Execution:
    - Supports non-blocking state machine execution with message queues.

6. Visualization:
    - Generates a Graphviz-compatible directed graph representation of state transitions.

Usage:
- Define custom states by inheriting from the `State` class and implementing required methods.
- Instantiate a `StateMachine` with initial, final, and error states.
- Use the `tick` method to process messages and transition between states.

Exceptions:
- `StateRetryLimitError`: Raised when a state exceeds its retry limit.
- `StateTimedOut`: Raised when a state exceeds its timeout duration.
- `MissingOnStateHandler`: Raised when a state does not define an `on_state` handler.
- `EmptyStateStackError`: Raised when attempting to pop from an empty state stack.
- `NoPushedStatesError`: Raised when no states are provided to a `Push` transition.
- `NonBlockingStalled`: Raised when a non-blocking FSM stalls.
- `BlockedInUntimedState`: Raised when the FSM is blocked in a state without a timeout.

"""

import collections
from dataclasses import dataclass, field
from datetime import datetime
from queue import Queue
from threading import Timer
from typing import Any


class StateRetryLimitError(Exception):
    pass


class StateMachineComplete(Exception):
    pass


class MissingOnStateHandler(Exception):
    pass


class StateTimedOut(Exception):
    pass


class InvalidPushError(Exception):
    pass


class EmptyStateStackError(Exception):
    pass


class NoPushedStatesError(Exception):
    pass


class NonBlockingStalled(Exception):
    pass


class BlockedInUntimedState(Exception):
    def __init__(self, state):
        super().__init__(f"Blocking on state without a timer: {state_name(state)}")
        self.state = state


def state_name(descriptor):
    if hasattr(descriptor, "__name__"):
        return descriptor.__name__
    elif hasattr(descriptor, "name"):
        return descriptor.name


def base_state_name(descriptor):
    if hasattr(descriptor, "__bases__"):
        return descriptor.__bases__[0].__name__
    elif hasattr(descriptor, "__class__"):
        return descriptor.__class__.__bases__[0].__name__


class State:
    """States are the workhorses of the enoki library. User states
    should inherit from State and provide on_enter/on_leave/on_fail/on_timeout
    methods (as appropriate, pass-through defaults are provided), and MUST
    provide on on_state handler.

    on_enter/on_leave are fired once on entry and on leaving the state. These
    methods should return nothing as they are incapable of affecting the
    transitioning of the state machine.

    on_state is the main/required method of each state. on_state should return
    one of several options:

    * Returning 'None' (or simply letting the function exit) indicates that the
    FSM will remain in the current state, and that if there was a message passed
    in, it was not handled (which will cause the message to be trapped by the
    encapsulating FSM). On the next tick, the state will begin from its on_state
    method. Note that this is essentially a 'wait' and if the state does not
    have a timeout defined, and it is not included in the FSM's 'dwell states',
    an error will be thrown as the FSM could otherwise be stalled indefinitely
    (See the section on TIMEOUT).

    * Returning 'Repeat' indicates that the state swallowed the message that
    it was passed. On the next tick, the same state will begin from its on_enter
    method. This is a transition from the current state back to a new instance
    of the same state.

    * Returning the constructor (not an instance!) of the current state will
    immediately retry the current state starting from on_enter. This will cause
    the FSM's retry counter to be decremented, and if the retry limit is
    reached, the on_fail handler will be called.

    * Returning another state's constructor (Not an instance!) is a
    transition. The FSM will fire the current on_leave handler (if it exists)
    and transition to the next state, first calling its on_enter, and then it's
    on_state handler. This is the most common way to transition between states.

    * Returning 'Push' with any number of state constructors as 
    arguments will transtiion to the first state and push the  rest onto the
    state stack. Example: Push(State1, State2, State3) would transition to
    State1 and then when a 'Pop' is encountered, State2 would be popped off the
    stack and transitioned to. Note that 'Pushing' a single state is
    functionally equivalent to a 'Transition' to that state.

    * Returning 'Pop' will pop the top state off the stack and transition to
    that state. If the stack is empty, an EmptyStateStackError will be raised.

    States may also provide TIMEOUT and RETRIES class variables.

    TIMEOUT specifies the duration of a failsafe timer in seconds that is
    started when a state is entered, and cancelled when a state successfully
    transitions. If the user has provided an on_timeout state, it will be called
    in response to this event. on_timeout may return None, which will cause the
    state machine's default error state to be entered, the descriptor of the
    current state, which will reset the timer, or the descriptor of a specific
    error state. 

    RETRIES specifies how many times a state may be retried before an error
    condition is flagged (default is None (infinite)). When this error condition
    occurs, the 'on_fail' handler will be called if it exists. on_fail may
    return None, which will cause the state machine's default error state to be
    entered, or the descriptor of a specific error state may be returned.

    """

    # TIMEOUT and RETRIES can and should be overridden by child
    # classes that require either of these bits of functionality
    TIMEOUT = None
    RETRIES = None

    def __init__(self):
        self._tries = None
        self._failsafe_timer = None
        self._reset()

    def _reset(self):
        if self.RETRIES is not None:
            self._tries = self.RETRIES + 1
        else:
            self._tries = None
        self._cancel_failsafe()
        self.has_entered = False

    def on_enter(self, shared):
        pass

    def on_leave(self, shared):
        pass

    def on_fail(self, shared):
        pass

    def on_timeout(self, shared):
        return self

    def _cancel_failsafe(self):
        if self._failsafe_timer:
            self._failsafe_timer.cancel()
            self._failsafe_timer = None

    def _start_failsafe(self, evt):
        self._failsafe_timer = evt.fsm.start_failsafe_timer(self.TIMEOUT)
        self._failsafe_timer.start()

    def _handle_retries(self):
        if self._tries is None:
            return
        elif self._tries == 0:
            raise StateRetryLimitError(
                f"State: {self.name} exceeded its maximum retry limit of {self.RETRIES} (retries {self._tries})"
            )

        self._tries -= 1

    def _maybe_failsafe_timer(self, evt):
        if self.TIMEOUT:
            self._cancel_failsafe()
            self._start_failsafe(evt)

    def _wrap_enter(self, evt, fn=None):
        self._handle_retries()

        if fn:
            fn(evt)

        self._maybe_failsafe_timer(evt)
        self.has_entered = True

    def _wrap_leave(self, evt, fn=None):
        if fn:
            fn(evt)
        self._reset()

    def _handle_timeout(self, shared_state):
        result = self.on_timeout(shared_state)
        if not result:
            result = shared_state.fsm._err_st

        # If we return ourselves from a timeout, this means that this
        # is a 'self ticking' state and we need to check our retries
        # and reset our timer
        if result is not None and state_name(result) == self.name:
            self.has_entered = False
            # Make sure that our timer is cancelled (in case out of order)
            self._cancel_failsafe()
            if isinstance(shared_state.msg, Exception):
                shared_state.msg = None

        return result

    def tick(self, shared_state):
        result = None

        if isinstance(shared_state.msg, StateTimedOut):
            result = self._handle_timeout(shared_state)
            return result
        elif isinstance(shared_state.msg, StateRetryLimitError):
            result = self.on_fail(shared_state)
            if not result:
                result = shared_state.fsm._err_st
            return result
        else:
            if not self.has_entered:
                self.on_enter_handler(shared_state)

            result = self.on_state_handler(shared_state)

            # Early exit, this is a wait condition
            if result in BLOCKING_RETURNS:
                return result

            # If a State intentionally returns itself, this is a retry and
            # we should re-enter on the next tick
            if result == type(self):
                self.has_entered = False
                self._cancel_failsafe()
                return result

        # If we got a new state, we should fire our on_leave handler,
        # and the next state's on_enter, then return the new state
        self.on_leave_handler(shared_state)
        return result

    @property
    def name(self):
        return self.__class__.__name__

    def on_enter_handler(self, evt):
        return self._wrap_enter(evt, self.on_enter)

    def on_state_handler(self, evt):
        if hasattr(self, "on_state"):
            return self.on_state(evt)
        else:
            raise MissingOnStateHandler(f"State {self.name} has no on_state handler!")

    def on_leave_handler(self, evt):
        return self._wrap_leave(evt, self.on_leave)


@dataclass
class TransitionType:
    def name(self):
        return self.__class__.__name__


@dataclass(init=False)
class Push(TransitionType):
    """
    Represents a transition type where one or more states are pushed onto the stack.

    Args:
        *push_states (List[Type[State]]): A variable number of state classes to be pushed onto the stack.
    """

    push_states: list[type[State]]

    def __init__(self, *push_states: list[type[State]]):
        self.push_states = push_states


@dataclass
class Pop(TransitionType):
    pass


@dataclass
class Repeat(TransitionType):
    pass


# NOTE: typically I'd define this above the State class, but I want to use
# `State` for the push type definition and didn't want to separate where they're
# defined
BLOCKING_RETURNS = [None, Repeat]


# End is a default state that any FSM can use
class DefaultStates:
    class End(State):
        def on_state(self, evt):
            pass


@dataclass
class GenericCommon:
    """This is an empty container class to hold any carry-over state in
    between FSM states should the user not provide a state container.

    """


@dataclass
class SharedState:
    """SharedState is passed to each state to allow states to share
    information downstream. The shared state object contains a
    reference to the higher level state machine (SharedState.fsm) and
    a common state object (SharedState.common), which may be user
    supplied during state machine instantiation.

    """

    fsm: "StateMachine"
    common: Any = field(default_factory=GenericCommon)


class StateMachine:
    """The StateMachine object is responsible for managing state
    transitions and bookkeeping shared state. On instantiation, the
    user must supply initial, final, and default error states (which
    must be subclasses of State).

    Additionally, the user MAY supply a Queue object (msg_queue) which will be
    used to pass messages into states (and relay information about timeouts and
    retry failures between the states and FSM). If no msg_queue is provided
    a default queue.Queue().empty() is used.

    The user MAY supply filter and trap functions. filter allows the
    user to pre-screen messages that may be important to the state
    machine machine, but might not be necessary to transition a state.
    trap will capture any unhandled message and can be used to raise
    exceptions or log notification messages.

    The state machine will raise an error if it stops in a state that has
    neither a timeout nor is the final state unless it is included in an
    iterable called dwell_states.

    (For a visual overview of the data flow, see enoki_data_flow.png)

    Finally, the user MAY supply a common_data class instance. This
    will be passed into each state and can be used to propagate
    information between states. If no common_data class is provided,
    an empty 'GenericCommon' will be provided (which is simply an empty class)

    """

    def __init__(
        self,
        initial_state,
        final_state,
        default_error_state,
        msg_queue=None,
        filter_fn=None,
        trap_fn=None,
        on_error_fn=None,
        log_fn=print,
        transition_fn=None,
        common_data=None,
        dwell_states=None,
    ):

        # We want to make sure that initial/final/default_err states
        # are descriptors, not instances
        for state in [initial_state, final_state, default_error_state]:
            if isinstance(state, State):
                raise TypeError(
                    "initial/final/default_error states must be class "
                    "descriptors, not instances"
                )

        self._initial_st = initial_state
        self._final_st = final_state
        self._err_st = default_error_state
        self._msg_queue = msg_queue or Queue()
        self._timeout_queue = Queue()
        self._log_fn = log_fn
        self._transition_fn = transition_fn
        self._on_err_fn = on_error_fn

        # Used for pushdown states
        self._state_stack = []

        self._current = None
        self._finished = False

        self.reset_transitions()

        self._last_trans_time = datetime.now()

        # The filter and trap functions are used to filter messages
        # (for example, common messages that apply to the process
        # rather than an individual state) and trap unhandled messages
        # (so that one could, for example, raise an exception)
        self._filter_fn = filter_fn
        self._trap_fn = trap_fn

        self._shared_state = SharedState(self, common_data)
        self._dwell_states = dwell_states or []

        self.reset()

    def start_failsafe_timer(self, duration):
        def _wrap_timeout(state, timeout):
            exception = StateTimedOut(
                f"State {state} timed out after {timeout} seconds"
            )
            self._timeout_queue.put(exception)
            # No-op to make sure tick state machine
            self._msg_queue.put(None)

        return Timer(
            duration,
            lambda x, y: _wrap_timeout(x, y),
            args=[self._current.name, duration],
        )

    def reset_transitions(self):
        # We store transitions and times separately since we don't
        # want slightly different times to affect the set of actual transitions
        self._transition_id = 0
        self._transitions = set()
        self._transition_times = collections.defaultdict(list)

    def _transition(self, trans_state):
        # If the next state is a Push, save the push states on the
        # state stack and transition to the next state, if a pop, then
        # try to pull the top state off of the stack. Otherwise, just
        # transition to the state provided
        if isinstance(trans_state, Push):
            if not len(trans_state.push_states):
                raise NoPushedStatesError("No states provided to push onto the stack")
            # Push the states on the stack in reverse order, keeping
            # the first state for the transition
            for state in reversed(trans_state.push_states[1:]):
                self._state_stack.append(state)
            next_state = trans_state.push_states[0]
        elif isinstance(trans_state, Pop):
            if len(self._state_stack) == 0:
                raise EmptyStateStackError("No states on stack!")
            next_state = self._state_stack.pop()
        else:
            next_state = trans_state

        # Calculate time deltas for each transition
        trans_time = datetime.now()
        trans_delta = (trans_time - self._last_trans_time).total_seconds()
        self._last_trans_time = trans_time

        if self._current:
            cur_name = state_name(self._current)
            cur_base = base_state_name(self._current)
        else:
            cur_name = "None"
            cur_base = "None"

        next_name = state_name(next_state)
        next_base = base_state_name(next_state)
        trans_tup = (cur_base, cur_name, next_base, next_name)

        self._transitions.add(trans_tup)
        self._transition_times[trans_tup].append((self._transition_id, trans_delta))
        self._transition_id += 1

        if self._log_fn:
            self._log_fn(f"State Transition: {cur_name} -> {next_name}")
        if self._transition_fn:
            self._transition_fn(next_state, self._shared_state)
        # If we are preempting another state and haven't cleaned
        # up the last state, reset it without calling on_leave_handler
        if self._current and self._current.has_entered:
            self._current._reset()

        self._current = next_state()

    @property
    def mermaid_flowchart(self):
        result = "flowchart LR\n"
        clusters = collections.defaultdict(set)
        transitions = ""
        cluster_transitions = set()
        for trans_tup in self._transitions:
            (first_base, first, second_base, second) = trans_tup

            clusters[first_base].add(first)
            clusters[second_base].add(second)
            deltas = self._transition_times[trans_tup]
            min_delta = min(deltas, key=lambda x: x[1])[1]
            max_delta = max(deltas, key=lambda x: x[1])[1]
            mean_delta = sum([x[1] for x in deltas]) / len(deltas)
            print(f"min: {min_delta}, max: {max_delta}, mean: {mean_delta}")
            delta_str = f"{min_delta:.2f} - {max_delta:.2f} ({mean_delta:.2f})"
            transitions += f'  {first} -->|"{delta_str}"| {second}\n'

        # Add clusters
        for cname, cluster in clusters.items():
            if cname == "None":
                continue
            result += f"  subgraph {cname}\n"
            for node in cluster:
                result += f"    {node}\n"
            result += "  end\n"

        result += transitions
        result += "\n"
        return result

    def save_mermaid_flowchart(self, filename):
        with open(filename, "w") as f:
            f.write(self.mermaid_flowchart)

    @property
    def graphviz_digraph(self):
        result = "digraph State {\n\trankdir=LR;\n\tnodesep=0.5;\n"
        clusters = collections.defaultdict(set)
        transitions = ""
        cluster_transitions = set()
        for trans_tup in self._transitions:
            (first_base, first, second_base, second) = trans_tup
            clusters[first_base].add(first)
            clusters[second_base].add(second)
            cluster_transitions.add(f"{first_base}->{second_base}")
            trans_deltas = self._transition_times[trans_tup]
            trans_deltas_strs = [f"{t_id}: {time:.2}" for t_id, time in trans_deltas]
            transitions += '{}->{} [ label="{}" ];\n'.format(
                first, second, "\n".join(trans_deltas_strs)
            )

        for cname, cluster in clusters.items():
            result += f"\tsubgraph cluster_{cname} {{\n"
            result += f'\t\tlabel="{cname}"'
            for node in cluster:
                result += f"\t\t{node};\n"
            result += "\tcolor=black;\n"
            result += "\t}\n\n"

        result += transitions
        result += "}\n"
        return result

    def save_graphviz_digraph(self, filename):
        with open(filename, "w") as f:
            f.write(self.graphviz_digraph)

    def reset(self):
        self._is_finished = False
        self._transition(self._initial_st)

    def clear_state_stack(self):
        self._state_stack = []
        
    @property
    def current_state_stack(self):
        """Returns a copy of the current state stack."""
        return self._state_stack.copy()

    def cleanup(self):
        if self._current:
            self._current._cancel_failsafe()

    @property
    def is_finished(self):
        return self._is_finished

    def start_non_blocking(self):
        self._msg_queue.put(None)
        # Still need while loop for getting errors pushed into queue
        while True:
            try:
                # Still check messages for RetryLimitException
                msg = self._msg_queue.get()
                self.tick(msg)
            except StateMachineComplete:
                raise
            if self._msg_queue.empty():
                raise NonBlockingStalled(
                    f"Non-blocking state machine stalled in {state_name(self._current)}"
                )

    def tick(self, message=None):
        self._shared_state.msg = message

        # If this is a filtered message, no reason to call the state
        # machine

        is_error_state = isinstance(message, Exception)
        ok_to_filter = bool(message and self._filter_fn and not is_error_state)

        filter_exception = None
        try:
            if ok_to_filter and self._filter_fn(self._shared_state):
                return
        except Exception as e:
            # Catching any exceptions raised from filtered messages
            #  to raise them later in the try to pass to the on_error function
            filter_exception = e

        fsm_busy = True
        while fsm_busy:
            try:
                if isinstance(self._current, self._final_st):
                    self._is_finished = True

                if not self._timeout_queue.empty():
                    raise self._timeout_queue.get()

                if filter_exception:
                    raise filter_exception

                next_state = self._current.tick(self._shared_state)

                if next_state in BLOCKING_RETURNS:
                    # If we didn't return anything at all, or we
                    # returned that we swallowed the message, we'll
                    # assume that the FSM is no longer busy and is
                    # waiting on some external message to move the
                    # state along

                    fsm_busy = False

                    # Additionally, if there is a message, and we
                    # returned nothing, we'll assume that the state
                    # didn't handle the message, and trap it.
                    should_trap = (
                        self._shared_state.msg and next_state is None and self._trap_fn
                    )

                    if should_trap:
                        self._trap_fn(self._shared_state)

                elif next_state:
                    # If we returned any state clear the message
                    self._shared_state.msg = None
                    if state_name(next_state) != self._current.name:
                        # Make sure timeouts are contained to their own state
                        if not self._timeout_queue.empty():
                            self._log_fn(
                                "Timed out while executing state. " "Moving on anyway."
                            )
                            # drop timeout on the floor
                            e = self._timeout_queue.get()
                            self._log_fn(str(e))
                        # Set our current state to the next state
                        self._transition(next_state)

                fsm_busy = fsm_busy and self._msg_queue.empty()
            except (StateRetryLimitError, StateTimedOut) as e:
                self._msg_queue.put(e)
                break
            except Exception as e:
                # While it's true that 'Pokemon errors' are typically
                # in poor taste, this allows the user to selectively
                # handle error cases, and throw any error that isn't
                # explicitely handled
                next_state = None
                filter_exception = None
                if self._on_err_fn:
                    next_state = self._on_err_fn(self._shared_state, e)
                if next_state:
                    self._transition(next_state)
                else:
                    raise e

        if self.is_finished:
            raise StateMachineComplete

        # If the state machine hasn't finished and the current state doesn't
        # have a timeout or isn't in one of the dwell_states passed in when
        # creating the state machine at the end of a tick an exception is
        # raised to indicate that the state machine is stalled.
        if (
            self._msg_queue.empty()
            and self._current.TIMEOUT is None
            and not any(
                [isinstance(self._current, d_state) for d_state in self._dwell_states]
            )
        ):
            raise BlockedInUntimedState(self._current)

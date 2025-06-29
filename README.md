# Enoki - A python state machine framework

Enoki is a finite state machine library for asynchronous event based
systems.


## Features

- **State Lifecycle Management**: Complete control over state entry, execution, and exit
- **Retry and Timeout Support**: Built-in mechanisms for handling transient failures and preventing deadlocks
- **Pushdown Automata**: State stack support for complex state hierarchies
- **Message-Driven Architecture**: Event-driven state transitions with message queues
- **Shared State Management**: Pass data between states seamlessly
- **Error Handling**: Comprehensive exception handling with custom error states
- **Visualization**: Generate Graphviz and Mermaid diagrams of state transitions
- **Non-blocking Execution**: Support for both blocking and non-blocking state machine execution

## Quick Start

### Basic Example

```python
import enoki
from enoki import State

class Ping(State):
    def on_state(self, shared_state):
        print("Ping!")
        return Pong

class Pong(State):
    def on_state(self, shared_state):
        print("Pong!")
        return Ping

class ErrorState(State):
    def on_state(self, shared_state):
        print("Error occurred")

# Create and run the state machine
fsm = enoki.StateMachine(
    initial_state=Ping,
    error_state=ErrorState
)

# Single step execution
fsm.tick()  # Prints "Ping!" and transitions to Pong
```

## Core Concepts


### States

States are the fundamental building blocks of your FSM. Each state inherits from the `State` base class and implements lifecycle methods:

- **`on_enter(shared_state)`**: Called when entering the state
- **`on_state(shared_state)`**: Main state logic (required)
- **`on_leave(shared_state)`**: Called when leaving the state
- **`on_fail(shared_state)`**: Called when retry limit is exceeded
- **`on_timeout(shared_state)`**: Called when state timeout occurs

States can also define optional parameters:

- **`TIMEOUT`**: Timeout in seconds; if set, the FSM will call `on_timeout` if the state waits too long for a message.
- **`RETRIES`**: Number of retries before failure; if set, the FSM will call `on_fail` when the retry limit is exceeded.
- **`TERMINAL`**: If set to `True`, marks the state as terminal and causes the FSM to exit when reached.
- **`CAN_DWELL`**: If set to `True`, allows the state to wait indefinitely for messages, even without a timeout.

```python
class ExampleState(State):
    TIMEOUT = 30    # Optional: timeout in seconds
    RETRIES = 3     # Optional: number of retries before failure
    TERMINAL = False  # Optional: mark as terminal state
    CAN_DWELL = False # Optional: allow indefinite waiting
    
    def on_enter(self, shared_state):
        print("Entering state")
    
    def on_state(self, shared_state):
        # Your state logic here
        if some_condition:
            return NextState    # Transition to NextState
        elif should_retry:
            return ExampleState   # Retry current state (decrements retry counter)
        else:
            return         # Stay in current state (wait)
    
    def on_leave(self, shared_state):
        print("Leaving state")
```


### Transitions

States can return different values to control transitions:

- **`NextState`**: Transition to a different state
- **`Again`**: Immediate continuation; re-enters the current state from `on_state` (does not reset retries/timer)
- **`Repeat`**: Renewal; restarts the current state from `on_enter` (resets retries/timer)
- **`Restart`**: Resets the retry counter, re-enters the state from `on_enter`, and waits for the next message
- **`Retry`**: Decrements the retry counter, re-enters the state from `on_enter` immediately
- **`Push(State1, State2, ...)`**: Push states onto stack and transition to the first
- **`Pop`**: Pop and transition to the top state from stack
- **`None`** or **`Unhandled`**: Stay in current state (wait for next message)

### Shared State

The `SharedState` object is passed to all state methods and contains:

- **`fsm`**: Reference to the state machine
- **`common`**: Shared data object for passing information between states
- **`msg`**: Current message being processed

```python
class DataProcessor(State):
    def on_state(self, shared_state):
        # Access shared data
        shared_state.common.processed_count += 1
        
        # Check current message
        if shared_state.msg and shared_state.msg['type'] == 'data':
            # Process the message
            return ProcessingComplete
        
        return None  # Wait for more messages
```

## Advanced Features

### Message-Driven State Machines

Message-driven state machines handle external events and messages using an internal queue. Use `send_message()` to enqueue messages for processing:

```python
fsm = enoki.StateMachine(
    initial_state=WaitingState,
    error_state=ErrorState,
    trap_fn=handle_unprocessed_messages  # Optional message handler
)

# Send messages to the state machine
fsm.send_message({'type': 'start', 'data': 'hello'})

# Process messages
while not fsm.is_finished:
    fsm.tick()  # Processes the next message in the queue
```

> **Note:** The state machine manages its own internal message queue. Use `send_message()` to add messages and `tick()` to process them.

### State Stack (Pushdown Automata)

Use `Push` and `Pop` for hierarchical state management:

```python
class MainMenu(State):
    def on_state(self, shared_state):
        if shared_state.msg['action'] == 'enter_submenu':
            # Push current state and transition to submenu
            return Push(SubMenu, SubMenuOption1, SubMenuOption2)

class SubMenu(State):
    def on_state(self, shared_state):
        if shared_state.msg['action'] == 'back':
            # Return to previous state
            return Pop
```

### Retry and Timeout Handling

Enoki is designed for asynchronous systems where operations are initiated in `on_enter` and responses are handled in `on_state`:

```python
class NetworkRequest(State):
    TIMEOUT = 10    # 10 second timeout
    RETRIES = 3     # Retry up to 3 times
    
    def on_enter(self, shared_state):
        # Initiate the async operation when entering the state
        self.request_id = send_network_request_async()
        print(f"Sent network request {self.request_id}")
    
    def on_state(self, shared_state):
        # Check for response messages
        if shared_state.msg and shared_state.msg.get('request_id') == self.request_id:
            if shared_state.msg['status'] == 'success':
                return ProcessResponse
            elif shared_state.msg['status'] == 'error':
                return type(self)  # Retry the request
        
        # No matching response yet, keep waiting
        return None
    
    def on_timeout(self, shared_state):
        print("Network request timed out")
        return type(self)  # Retry on timeout
    
    def on_fail(self, shared_state):
        print("Network request failed after all retries")
        return ErrorState
```

### Shared State Between States

```python
class DataContainer:
    def __init__(self):
        self.user_data = {}
        self.session_id = None

fsm = enoki.StateMachine(
    initial_state=LoginState,
    error_state=ErrorState,
    common_data=DataContainer()
)
```

## Message Filtering and Trapping

Enoki provides two mechanisms for handling messages that don't need to reach individual states:

*Filter Function*: Pre-processes messages before they reach states. If the filter returns True, the message is consumed and won't be passed to the current state. Useful for handling global messages like heartbeats or status updates.

*Trap Function*: Handles messages that states don't process (when on_state returns None). This catches "unhandled" messages and can be used for logging, error reporting, or default processing.

```python
def message_filter(shared_state):
    # Handle global messages that don't need state-specific processing
    if shared_state.msg and shared_state.msg.get('type') == 'heartbeat':
        shared_state.common.last_heartbeat = time.time()
        return True  # Message consumed, don't pass to state
    return False  # Let state handle the message

def message_trap(shared_state):
    # Handle messages that states didn't process
    msg = shared_state.msg
    if msg:
        print(f"Unhandled message in state {shared_state.fsm._current.name}: {msg}")
        # Could log, raise exception, or take other action

fsm = enoki.StateMachine(
    initial_state=StartState,
    error_state=ErrorState,
    filter_fn=message_filter,
    trap_fn=message_trap
)
```

## State Machine Configuration

The `StateMachine` constructor accepts several configuration options:

```python
fsm = enoki.StateMachine(
    initial_state=StartState,           # Required: Starting state
    error_state=ErrorState,     # Required: Default error handler
    filter_fn=message_filter,           # Optional: Pre-filter messages
    trap_fn=handle_unprocessed,         # Optional: Handle unprocessed messages
    on_error_fn=error_handler,          # Optional: Global error handler
    log_fn=print,                       # Optional: Logging function
    transition_fn=log_transitions,      # Optional: Transition callback
    common_data=SharedData()            # Optional: Shared state object
)
```

## Visualization

Generate visual representations of your state machine:

```python
# Generate Mermaid flowchart
fsm.save_mermaid_flowchart('state_diagram.mmd')

# Generate Graphviz digraph
fsm.save_graphviz_digraph('state_diagram.dot')
```

## Examples

The library includes several complete examples:

### 1. Free-Running State Machine (`freerun.py`)
Demonstrates a simple ping-pong state machine with retry logic that runs indefinitely.

### 2. Message-Driven State Machine (`blocking.py`)
Shows how to create a state machine that waits for specific messages, with shared state management and message trapping.

### 3. Event-Driven State Machine (`event_driven.py`)
Illustrates timeout handling and dwell states in an event-driven architecture.

## Error Handling

Enoki provides comprehensive error handling:
- **`StateRetryLimitError`**: Raised when a state exceeds its retry limit
- **`StateTimedOut`**: Raised when a state exceeds its timeout duration
- **`MissingOnStateHandler`**: Raised when a state lacks the required `on_state` method
- **`EmptyStateStackError`**: Raised when attempting to pop from an empty state stack
- **`BlockedInUntimedState`**: Raised when FSM is blocked in a state without timeout

## Best Practices

1. **Always implement `on_state`**: This is the only required method for states
2. **Use timeouts for blocking states**: Prevent infinite waits with `TIMEOUT`
3. **Handle retries gracefully**: Implement `on_fail` for retry limit scenarios
4. **Use shared state for data flow**: Pass information between states via `common`
5. **Implement proper error states**: Always provide meaningful error handling
6. **Leverage state stacks**: Use `Push`/`Pop` for hierarchical state management

## Installation

```bash
# Copy enoki.py to your project directory
# No external dependencies required - uses only Python standard library
```

## License

Enoki is released under the MIT License. See the [LICENSE](LICENSE) file for details.


## Requirements

* Python >= 3.10
* GraphViz (Optional for state machine visualization)

## Authors

Enoki was originally developed at [Keyme](www.key.me) under the name Mortise by [Jeff Ciesielski](https://github.com/Jeff-Ciesielski) and [Lianne Lairmore](https://github.com/knithacker) for robotics control.

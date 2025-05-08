#!/usr/bin/env python3

import queue
import threading
import time

import enoki
from enoki import State


class Ping(State):
    TIMEOUT = 10

    def on_state(self, st):
        if st.msg:
            print("Ping: ", st.msg['data'])
            return Pong


class Pong(State):
    def on_state(self, st):
        if st.msg:
            print("Pong: ", st.msg['data'])
            return Ping


class ErrorState(State):
    def on_state(self, st):
        pass


def loop(msg_queue):
    # msg_queue should be accessible to another thread which is
    # handling IPC traffic or otherwise generating events to be
    # consumed by the state machine

    fsm = enoki.StateMachine(
        initial_state=Ping,
        final_state=enoki.DefaultStates.End,
        default_error_state=ErrorState,
        msg_queue=msg_queue,
        log_fn=print,
        dwell_states=[Pong])

    # Initial kick of the state machine for setup
    fsm.tick()

    while True:
        fsm.tick(msg_queue.get())


def msg_loop(msg_queue):
    # NOTE: The messages consumed by enoki are content agnostic, the
    # implementation / checking of message type is up to the user.

    idx = 0
    while True:
        messages = ['foo', 'bar', 'baz']
        idx += 1
        idx %= len(messages)
        msg_queue.put({'data': messages[idx]})
        time.sleep(1)


def main():
    msg_queue = queue.Queue()
    enoki_t = threading.Thread(target=loop, kwargs={'msg_queue': msg_queue})
    msg_t = threading.Thread(target=msg_loop, kwargs={'msg_queue': msg_queue})

    enoki_t.daemon = True
    msg_t.daemon = True

    enoki_t.start()
    msg_t.start()

    enoki_t.join()
    msg_t.join()

main()

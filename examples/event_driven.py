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
    CAN_DWELL=True
    def on_state(self, st):
        if st.msg:
            print("Pong: ", st.msg['data'])
            return Ping


class ErrorState(State):
    def on_state(self, st):
        pass


def loop(msg_queue):
    fsm = enoki.StateMachine(
        initial_state=Ping,
        error_state=ErrorState,
        log_fn=print)

    # Initial kick of the state machine for setup
    fsm.tick()

    while True:
        msg = msg_queue.get()
        fsm.send_message(msg)
        fsm.tick()


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
